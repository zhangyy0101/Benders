"""Synthetic rolling-horizon data and closed-loop execution simulation.

Optimizer-visible snapshots contain external forecasts and planned release
times only. Hidden realized arrivals and realized release times are read solely
by :func:`advance_state`.
"""
from __future__ import annotations

import math
import random
from typing import Iterable

from config import (
    DEFAULT_OUTBOUND_BOXES_PER_6H,
    FORECAST_ERROR_CORRELATION,
    FORECAST_ERROR_MODES,
    FORECAST_MIN_SIGMA_RATIO,
    INITIAL_BAY_MAX_FILL_RATIO,
    INITIAL_UTILIZATION_TOLERANCE,
    LOOKAHEAD_HOURS,
    RECEIVING_WINDOW_HOURS,
    ROLLING_CYCLE_HOURS,
    SHIP_OPERATION_DURATION_RANGES,
    TIME_BUCKET_HOURS,
    VALIDATE_EACH_EXECUTION_PERIOD,
)

PERIOD_HOURS = TIME_BUCKET_HOURS
EXECUTION_PERIODS = ROLLING_CYCLE_HOURS // PERIOD_HOURS
RECEIVING_PERIODS = RECEIVING_WINDOW_HOURS // PERIOD_HOURS
LOOKAHEAD_PERIODS = LOOKAHEAD_HOURS // PERIOD_HOURS
INF = 10**9


def _integer_profile(total: int, weights: Iterable[float]) -> list[int]:
    """Distribute an integer total deterministically according to nonnegative weights."""
    weights = list(weights)
    if total <= 0:
        return [0] * len(weights)
    denominator = sum(weights)
    if denominator <= 0:
        weights = [1.0] * len(weights)
        denominator = float(len(weights))
    raw = [total * weight / denominator for weight in weights]
    base = [int(value) for value in raw]
    order = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - base[index]), index),
    )
    for index in order[: total - sum(base)]:
        base[index] += 1
    return base


def build_initial_locked_inventory(
    *,
    bays: Iterable[str],
    capacity: dict[str, int],
    bay_size: dict[str, int],
    heights: Iterable[str],
    target_utilization: float,
    seed: int,
    max_fill_ratio: float = INITIAL_BAY_MAX_FILL_RATIO,
) -> tuple[dict, dict, dict]:
    """Build an exact, heterogeneous initial inventory at the requested utilization."""
    ordered_bays = sorted(bays)
    height_values = tuple(heights)
    if not ordered_bays or not height_values:
        raise ValueError("bays and heights must be nonempty")
    if set(ordered_bays) != set(bay_size):
        raise ValueError("bay_size must be defined for every bay")
    if not 0 <= target_utilization <= 1:
        raise ValueError("target_utilization must be between zero and one")
    if not 0 < max_fill_ratio <= 1:
        raise ValueError("max_fill_ratio must be in (0, 1]")

    total_capacity = sum(capacity[bay] for bay in ordered_bays)
    target_quantity = round(total_capacity * target_utilization)
    fill_limit = {
        bay: math.floor(capacity[bay] * max_fill_ratio) for bay in ordered_bays
    }
    reachable = sum(fill_limit.values())
    if target_quantity > reachable:
        raise ValueError(
            "requested initial utilization is physically unreachable under "
            f"max_fill_ratio={max_fill_ratio}: target={target_quantity}, "
            f"reachable={reachable}"
        )

    rng = random.Random(seed + 31_337)
    weights = {
        bay: fill_limit[bay] * rng.uniform(.55, 1.45) for bay in ordered_bays
    }
    denominator = sum(weights.values()) or 1.0
    raw = {bay: target_quantity * weights[bay] / denominator for bay in ordered_bays}
    allocation = {
        bay: min(fill_limit[bay], math.floor(raw[bay])) for bay in ordered_bays
    }
    remaining = target_quantity - sum(allocation.values())
    priority = sorted(
        ordered_bays,
        key=lambda bay: (-(raw[bay] - math.floor(raw[bay])), rng.random(), bay),
    )
    while remaining:
        progressed = False
        for bay in priority:
            spare = fill_limit[bay] - allocation[bay]
            if spare <= 0:
                continue
            take = min(spare, max(1, math.ceil(remaining / len(priority))))
            allocation[bay] += take
            remaining -= take
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            raise RuntimeError("initial inventory allocation stalled unexpectedly")

    used_bays = [bay for bay in ordered_bays if allocation[bay] > 0]
    old_count = max(2, min(8, math.ceil(max(1, len(used_bays)) / 8)))
    old_ships = [f"OLD{index + 1:02d}" for index in range(old_count)]
    rng.shuffle(used_bays)
    locked: dict[tuple[str, str], int] = {}
    locked_height: dict[tuple[str, str], str] = {}
    for index, bay in enumerate(used_bays):
        old_ship = old_ships[index % old_count]
        key = (bay, old_ship)
        locked[key] = allocation[bay]
        locked_height[key] = height_values[rng.randrange(len(height_values))]

    realized_quantity = sum(locked.values())
    diagnostics = {
        "requested_initial_utilization": float(target_utilization),
        "realized_initial_utilization": (
            realized_quantity / total_capacity if total_capacity else 0.0
        ),
        "initial_locked_quantity": realized_quantity,
        "initial_total_capacity": total_capacity,
        "initialization_shortfall": target_quantity - realized_quantity,
    }
    if abs(realized_quantity - target_quantity) > INITIAL_UTILIZATION_TOLERANCE:
        raise RuntimeError(f"initial inventory target was not reached: {diagnostics}")
    return locked, locked_height, diagnostics


def _operation_duration(
    schedule_rng: random.Random,
    ship_index: int,
    configured: int | tuple[int, int] | None,
) -> tuple[str, int]:
    """Generate an external ship-operation duration independently of hidden demand."""
    ship_class = ("small", "medium", "large")[ship_index % 3]
    if isinstance(configured, int):
        return ship_class, max(1, configured)
    low, high = configured or SHIP_OPERATION_DURATION_RANGES[ship_class]
    return ship_class, schedule_rng.randint(max(1, low), max(1, high))


def generate_hidden_truth(
    *,
    booking_flow: dict[tuple[str, str, int], int],
    forecast_error_mode: str,
    error_level: float,
    seed: int,
    receiving_start: dict[str, int],
    eta_period: dict[str, int],
    groups: Iterable[str] | None = None,
) -> dict[tuple[str, str, int], int]:
    """Draw one final hidden realization from the public booking baseline."""
    if forecast_error_mode not in FORECAST_ERROR_MODES:
        raise ValueError(f"unsupported forecast error mode: {forecast_error_mode}")
    rng = random.Random(seed + 91_919)
    ships = sorted(receiving_start)
    group_values = sorted(groups or {group for _ship, group, _t in booking_flow})
    result: dict[tuple[str, str, int], int] = {}
    ship_factor = {
        ship: max(0.0, 1.0 + rng.gauss(0, error_level)) for ship in ships
    }
    pair_cancel: set[tuple[str, str]] = set()
    if forecast_error_mode in ("booking_add_cancel", "mixed"):
        pairs = sorted({(ship, group) for ship, group, _period in booking_flow})
        pair_cancel = {
            pair for pair in pairs if rng.random() < min(.40, error_level * .35)
        }

    for (ship, group, absolute), booked in sorted(booking_flow.items()):
        target_period = absolute
        timing_probability = error_level * (
            .55 if forecast_error_mode == "mixed" else 1.0
        )
        if (
            forecast_error_mode in ("timing_shift", "mixed")
            and rng.random() < timing_probability
        ):
            target_period += -1 if rng.random() < 0.5 else 1
            target_period = min(
                eta_period[ship] - 1,
                max(receiving_start[ship], target_period),
            )
        factor = 1.0
        if forecast_error_mode in ("multiplicative", "mixed"):
            factor *= max(
                0.0,
                1.0 + rng.gauss(0, error_level * (.55 if forecast_error_mode == "mixed" else 1.0)),
            )
        if forecast_error_mode in ("ship_correlated", "mixed"):
            factor *= ship_factor[ship]
            factor *= max(0.0, 1.0 + rng.gauss(0, error_level * .25))
        if (ship, group) in pair_cancel:
            factor = 0.0
        quantity = max(0, int(round(booked * factor)))
        if quantity:
            key = (ship, group, target_period)
            result[key] = result.get(key, 0) + quantity

    if forecast_error_mode in ("booking_add_cancel", "mixed") and error_level > 0:
        positive_pairs = {(ship, group) for ship, group, _period in booking_flow}
        for ship in ships:
            zero_groups = [
                group for group in group_values if (ship, group) not in positive_pairs
            ]
            if not zero_groups or rng.random() >= min(.75, error_level * 1.5):
                continue
            group = zero_groups[rng.randrange(len(zero_groups))]
            booked_total = sum(
                quantity
                for (j, _g, _period), quantity in booking_flow.items()
                if j == ship
            )
            added = max(1, int(round(booked_total * error_level * .10)))
            profile = _integer_profile(added, [1, 2, 3, 3, 2, 1])
            start = receiving_start[ship] + 3
            for offset, quantity in enumerate(profile):
                absolute = min(eta_period[ship] - 1, start + offset)
                if quantity:
                    key = (ship, group, absolute)
                    result[key] = result.get(key, 0) + quantity
    return result


def generate_forecast_trajectory(
    *,
    true_flow: dict[tuple[str, str, int], int],
    booking_flow: dict[tuple[str, str, int], int],
    cycles: int,
    forecast_error_mode: str,
    error_level: float,
    seed: int,
    receiving_start: dict[str, int],
    eta_period: dict[str, int],
) -> dict[tuple[int, str, str, int], int]:
    """Generate correlated forecasts whose uncertainty shrinks with lead time."""
    rng = random.Random(seed + 204_811)
    rho = FORECAST_ERROR_CORRELATION
    innovation_scale = math.sqrt(max(0.0, 1.0 - rho * rho))
    items = sorted(set(true_flow) | set(booking_flow))
    pairs = sorted({(ship, group) for ship, group, _period in items})
    ships = sorted({ship for ship, _group in pairs})
    item_error = {item: rng.gauss(0, 1) for item in items}
    pair_error = {pair: rng.gauss(0, 1) for pair in pairs}
    ship_error = {ship: rng.gauss(0, 1) for ship in ships}
    shift_draw = {item: rng.random() for item in items}
    shift_direction = {item: (-1 if rng.random() < .5 else 1) for item in items}
    forecasts: dict[tuple[int, str, str, int], int] = {}

    for cycle in range(cycles):
        now = cycle * EXECUTION_PERIODS
        for item in items:
            item_error[item] = (
                rho * item_error[item] + innovation_scale * rng.gauss(0, 1)
            )
        for pair in pairs:
            pair_error[pair] = (
                rho * pair_error[pair] + innovation_scale * rng.gauss(0, 1)
            )
        for ship in ships:
            ship_error[ship] = (
                rho * ship_error[ship] + innovation_scale * rng.gauss(0, 1)
            )

        for item in items:
            ship, group, absolute = item
            if absolute < now:
                continue
            truth = true_flow.get(item, 0)
            booked = booking_flow.get(item, 0)
            lead_ratio = min(1.0, max(0.0, (absolute - now) / RECEIVING_PERIODS))
            sigma_ratio = max(FORECAST_MIN_SIGMA_RATIO, lead_ratio)
            reveal = 1.0 - lead_ratio
            if forecast_error_mode in ("booking_add_cancel", "mixed"):
                center = booked + reveal * (truth - booked)
            else:
                center = float(truth)

            multiplier = 1.0
            if forecast_error_mode == "multiplicative":
                multiplier += error_level * sigma_ratio * item_error[item]
            elif forecast_error_mode == "ship_correlated":
                combined = .80 * ship_error[ship] + .20 * pair_error[ship, group]
                multiplier += error_level * sigma_ratio * combined
            elif forecast_error_mode == "mixed":
                combined = .60 * ship_error[ship] + .25 * pair_error[ship, group]
                combined += .15 * item_error[item]
                multiplier += .55 * error_level * sigma_ratio * combined
            quantity = max(0, int(round(center * max(0.0, multiplier))))
            target_period = absolute
            if forecast_error_mode in ("timing_shift", "mixed"):
                probability = error_level * sigma_ratio
                if forecast_error_mode == "mixed":
                    probability *= .55
                if shift_draw[item] < probability:
                    target_period += shift_direction[item]
                    target_period = min(
                        eta_period[ship] - 1,
                        max(receiving_start[ship], target_period),
                    )
            if quantity and target_period >= now:
                key = (cycle, ship, group, target_period)
                forecasts[key] = forecasts.get(key, 0) + quantity
    return forecasts


def forecast_trajectory_diagnostics(
    *,
    forecasts: dict[tuple[int, str, str, int], int],
    true_flow: dict[tuple[str, str, int], int],
    cycles: int,
) -> dict[str, dict[int, float]]:
    """Measure forecast quality by cycle without exposing diagnostics to the model."""
    mae: dict[int, float] = {}
    mape: dict[int, float] = {}
    total_error: dict[int, float] = {}
    timing_error: dict[int, float] = {}
    for cycle in range(cycles):
        now = cycle * EXECUTION_PERIODS
        truth = {
            key: quantity for key, quantity in true_flow.items() if key[2] >= now
        }
        predicted = {
            (ship, group, period): quantity
            for (r, ship, group, period), quantity in forecasts.items()
            if r == cycle and period >= now
        }
        keys = sorted(set(truth) | set(predicted))
        errors = [abs(predicted.get(key, 0) - truth.get(key, 0)) for key in keys]
        mae[cycle] = sum(errors) / max(1, len(errors))
        positive = [key for key in keys if truth.get(key, 0) > 0]
        mape[cycle] = sum(
            abs(predicted.get(key, 0) - truth[key]) / truth[key] for key in positive
        ) / max(1, len(positive))
        total_error[cycle] = abs(sum(predicted.values()) - sum(truth.values()))
        pair_values = sorted({(ship, group) for ship, group, _period in keys})
        centroid_errors = []
        for ship, group in pair_values:
            truth_total = sum(
                quantity for (j, g, _t), quantity in truth.items()
                if j == ship and g == group
            )
            predicted_total = sum(
                quantity for (j, g, _t), quantity in predicted.items()
                if j == ship and g == group
            )
            if not truth_total or not predicted_total:
                continue
            truth_center = sum(
                period * quantity
                for (j, g, period), quantity in truth.items()
                if j == ship and g == group
            ) / truth_total
            predicted_center = sum(
                period * quantity
                for (j, g, period), quantity in predicted.items()
                if j == ship and g == group
            ) / predicted_total
            centroid_errors.append(abs(predicted_center - truth_center))
        timing_error[cycle] = (
            sum(centroid_errors) / len(centroid_errors) if centroid_errors else 0.0
        )
    return {
        "forecast_mae_by_cycle": mae,
        "forecast_mape_by_cycle": mape,
        "forecast_total_error_by_cycle": total_error,
        "forecast_timing_error_by_cycle": timing_error,
    }


def build_synthetic_rolling_case(
    *,
    seed: int = 0,
    num_blocks: int = 8,
    bays_per_block: int = 8,
    num_ships: int = 8,
    cycles: int = 6,
    tail_execution_cycles: int = 0,
    bay_capacity: int = 50,
    initial_utilization: float = .25,
    forecast_error: float = .10,
    forecast_error_mode: str = "multiplicative",
    nominal_outbound_rate_per_ship_period: int = DEFAULT_OUTBOUND_BOXES_PER_6H,
    outbound_boxes_per_period: int | None = None,
    containers_per_ship_range: tuple[int, int] = (60, 160),
    ship_volume_factor: float = 1.0,
    active_ship_overlap: int = 2,
    pod_count: int = 3,
    ship_operation_duration_periods: int | tuple[int, int] | None = None,
    release_delay_periods: int | dict[str, int] = 0,
) -> dict:
    """Build a reproducible case with external ship schedules and hidden truth."""
    if outbound_boxes_per_period is not None:
        if (
            nominal_outbound_rate_per_ship_period
            != DEFAULT_OUTBOUND_BOXES_PER_6H
            and nominal_outbound_rate_per_ship_period != outbound_boxes_per_period
        ):
            raise ValueError("conflicting nominal and legacy outbound rates")
        nominal_outbound_rate_per_ship_period = outbound_boxes_per_period
    if nominal_outbound_rate_per_ship_period <= 0:
        raise ValueError("nominal_outbound_rate_per_ship_period must be positive")
    if forecast_error_mode not in FORECAST_ERROR_MODES:
        raise ValueError(f"forecast_error_mode must be one of {FORECAST_ERROR_MODES}")
    if not 0 <= initial_utilization <= 1:
        raise ValueError("initial_utilization must be between zero and one")
    if active_ship_overlap <= 0 or pod_count <= 0:
        raise ValueError("active_ship_overlap and pod_count must be positive")
    if cycles <= 0 or tail_execution_cycles < 0:
        raise ValueError("cycles must be positive and tail_execution_cycles nonnegative")
    low_boxes, high_boxes = containers_per_ship_range
    if low_boxes <= 0 or high_boxes < low_boxes:
        raise ValueError("containers_per_ship_range must be positive and ordered")
    if ship_volume_factor <= 0:
        raise ValueError("ship_volume_factor must be positive")

    rng = random.Random(seed)
    schedule_rng = random.Random(seed + 71_011)
    blocks = [f"B{index + 1:02d}" for index in range(num_blocks)]
    bays = [
        f"{block}_Y{position + 1:02d}"
        for block in blocks
        for position in range(bays_per_block)
    ]
    bay_block = {bay: bay.split("_Y")[0] for bay in bays}
    bay_size = {bay: 20 if index % 2 == 0 else 40 for index, bay in enumerate(bays)}
    capacity = {bay: int(bay_capacity) for bay in bays}
    heights = ("STD", "HIGH")
    pods = tuple(f"P{index + 1}" for index in range(pod_count))
    group_attrs = {
        f"{pod}_{size}_{height}": {"pod": pod, "size": size, "height": height}
        for pod in pods
        for size in (20, 40)
        for height in heights
    }
    groups = sorted(group_attrs)
    ships = [f"V{index + 1:02d}" for index in range(num_ships)]
    execution_cycles = cycles + tail_execution_cycles
    eta_period: dict[str, int] = {}
    receiving_start: dict[str, int] = {}
    planned_release: dict[str, int] = {}
    realized_release: dict[str, int] = {}
    ship_class: dict[str, str] = {}
    operation_duration: dict[str, int] = {}
    distance: dict[tuple[str, str], int] = {}
    booking_flow: dict[tuple[str, str, int], int] = {}
    triangle = [1, 2, 3, 4, 5, 6, 6, 5, 4, 3, 2, 1]

    for index, ship in enumerate(ships):
        admission_cycle = min(max(0, cycles - 1), index // active_ship_overlap)
        start = admission_cycle * EXECUTION_PERIODS + 1 + (index % EXECUTION_PERIODS)
        receiving_start[ship] = start
        eta_period[ship] = start + RECEIVING_PERIODS
        category, duration = _operation_duration(
            schedule_rng, index, ship_operation_duration_periods
        )
        ship_class[ship] = category
        berth = index % max(1, min(4, num_blocks))
        for block_index, block in enumerate(blocks):
            distance[ship, block] = 100 + 120 * abs(block_index - berth)

        eligible_groups = [
            f"{pod}_{size}_{heights[(index + pod_index + size // 20) % 2]}"
            for pod_index, pod in enumerate(pods)
            for size in (20, 40)
        ]
        selected = [group for group in eligible_groups if rng.random() < .78]
        if not selected:
            selected = [eligible_groups[0]]
        sampled_ship_total = rng.randint(low_boxes, high_boxes)
        ship_total = max(1, int(round(sampled_ship_total * ship_volume_factor)))
        volume_duration = math.ceil(
            ship_total / nominal_outbound_rate_per_ship_period
        )
        duration = max(duration, volume_duration)
        operation_duration[ship] = duration
        planned_release[ship] = eta_period[ship] + duration
        delay = (
            release_delay_periods.get(ship, 0)
            if isinstance(release_delay_periods, dict)
            else release_delay_periods
        )
        realized_release[ship] = planned_release[ship] + max(0, int(delay))
        group_quantities = _integer_profile(
            ship_total, [rng.uniform(.5, 1.5) for _group in selected]
        )
        for group, total in zip(selected, group_quantities):
            if total <= 0:
                continue
            for offset, quantity in enumerate(_integer_profile(total, triangle)):
                if quantity:
                    booking_flow[ship, group, start + offset] = quantity

    true_flow = generate_hidden_truth(
        booking_flow=booking_flow,
        forecast_error_mode=forecast_error_mode,
        error_level=forecast_error,
        seed=seed,
        receiving_start=receiving_start,
        eta_period=eta_period,
        groups=groups,
    )
    true_total: dict[tuple[str, str], int] = {}
    for (ship, group, _absolute), quantity in true_flow.items():
        true_total[ship, group] = true_total.get((ship, group), 0) + quantity

    forecasts = generate_forecast_trajectory(
        true_flow=true_flow,
        booking_flow=booking_flow,
        cycles=execution_cycles,
        forecast_error_mode=forecast_error_mode,
        error_level=forecast_error,
        seed=seed,
        receiving_start=receiving_start,
        eta_period=eta_period,
    )
    forecast_diagnostics = forecast_trajectory_diagnostics(
        forecasts=forecasts,
        true_flow=true_flow,
        cycles=execution_cycles,
    )

    locked, locked_height, initialization_diagnostics = (
        build_initial_locked_inventory(
            bays=bays,
            capacity=capacity,
            bay_size=bay_size,
            heights=heights,
            target_utilization=initial_utilization,
            seed=seed,
            max_fill_ratio=INITIAL_BAY_MAX_FILL_RATIO,
        )
    )
    old_release_period: dict[str, int] = {}

    old_outbound: dict[tuple[str, str, int], int] = {}
    for old_index, old_ship in enumerate(sorted({ship for _bay, ship in locked})):
        total = sum(quantity for (_bay, ship), quantity in locked.items() if ship == old_ship)
        duration = max(
            1,
            math.ceil(total / nominal_outbound_rate_per_ship_period),
        )
        start = old_index * EXECUTION_PERIODS
        old_release_period[old_ship] = start + duration
        block_remaining = {
            block: sum(
                quantity
                for (bay, ship), quantity in locked.items()
                if ship == old_ship and bay_block[bay] == block
            )
            for block in blocks
        }
        block_remaining = {block: value for block, value in block_remaining.items() if value}
        for offset, period_total in enumerate(_integer_profile(total, [1] * duration)):
            left = period_total
            while left > 0 and block_remaining:
                block = min(
                    block_remaining,
                    key=lambda item: (-block_remaining[item], item),
                )
                take = min(left, block_remaining[block])
                old_outbound[old_ship, block, start + offset] = take
                block_remaining[block] -= take
                left -= take
                if block_remaining[block] <= 0:
                    del block_remaining[block]

    ship_outbound: dict[tuple[str, int], int] = {}
    for ship in ships:
        total = sum(value for (j, _group), value in true_total.items() if j == ship)
        duration = max(1, realized_release[ship] - eta_period[ship])
        for offset, quantity in enumerate(_integer_profile(total, [1] * duration)):
            if quantity:
                ship_outbound[ship, eta_period[ship] + offset] = quantity

    outbound_forecasts: dict[tuple[int, str, str, int], int] = {}
    for cycle in range(execution_cycles):
        now = cycle * EXECUTION_PERIODS
        for (old_ship, block, absolute), truth in old_outbound.items():
            if absolute >= now:
                outbound_forecasts[cycle, old_ship, block, absolute] = truth

    return {
        "blocks": blocks,
        "bays": bays,
        "bay_block": bay_block,
        "bays_in_block": {
            block: [bay for bay in bays if bay_block[bay] == block]
            for block in blocks
        },
        "bay_size": bay_size,
        "capacity": capacity,
        "heights": heights,
        "ships": ships,
        "eta_period": eta_period,
        "receiving_start_period": receiving_start,
        "planned_ship_release_period": planned_release,
        "realized_ship_release_period": realized_release,
        "release_period_basis": "external_schedule",
        "ship_class": ship_class,
        "ship_operation_duration_periods": operation_duration,
        "release_delay_periods": release_delay_periods,
        "group_attrs": group_attrs,
        "true_total": true_total,
        "true_flow": true_flow,
        "booking_flow": booking_flow,
        "forecast_generation_basis": "hidden_truth_noisy_information_trajectory",
        "forecasts": forecasts,
        **forecast_diagnostics,
        "distance": distance,
        "locked_initial": locked,
        "locked_height_initial": locked_height,
        "old_release_period": old_release_period,
        "old_outbound_flow": old_outbound,
        "ship_outbound_flow": ship_outbound,
        "outbound_forecasts": outbound_forecasts,
        "outbound_boxes_per_period": nominal_outbound_rate_per_ship_period,
        "nominal_outbound_rate_per_ship_period": (
            nominal_outbound_rate_per_ship_period
        ),
        "cycles": cycles,
        "admission_cycles": cycles,
        "tail_execution_cycles": tail_execution_cycles,
        "execution_cycles": execution_cycles,
        "period_hours": PERIOD_HOURS,
        "execution_periods": EXECUTION_PERIODS,
        "receiving_periods": RECEIVING_PERIODS,
        "lookahead_periods": LOOKAHEAD_PERIODS,
        "seed": seed,
        "forecast_error": forecast_error,
        "forecast_error_mode": forecast_error_mode,
        "initial_utilization": initial_utilization,
        **initialization_diagnostics,
        "containers_per_ship_range": containers_per_ship_range,
        "ship_volume_factor": float(ship_volume_factor),
        "effective_containers_per_ship_range": (
            max(1, int(round(low_boxes * ship_volume_factor))),
            max(1, int(round(high_boxes * ship_volume_factor))),
        ),
        "active_ship_overlap": active_ship_overlap,
        "pod_count": pod_count,
        "num_blocks": num_blocks,
        "bays_per_block": bays_per_block,
        "num_ships": num_ships,
    }


def build_oracle_certified_case_family(
    *,
    factor_bounds: tuple[float, float] = (.25, 4.0),
    feasible_fraction: float = .75,
    boundary_relative_tolerance: float = .05,
    search_iterations: int = 8,
    oracle_time_limit: float = 60.0,
    oracle_threads: int = 1,
    oracle_seed: int | None = None,
    **synthetic_case_kwargs,
) -> dict:
    """Build ordinary-feasible, tight-feasible, and overloaded sister cases.

    Every returned label is backed by the independent full-information integer
    packing oracle.  The tight case is the largest certified-feasible volume
    factor found immediately below a certified-overloaded factor.  Unknown
    oracle results stop calibration instead of being treated as infeasibility.
    """
    if "ship_volume_factor" in synthetic_case_kwargs:
        raise ValueError(
            "ship_volume_factor is calibrated internally and must not be supplied"
        )
    lower_factor, upper_factor = map(float, factor_bounds)
    if lower_factor <= 0 or upper_factor <= lower_factor:
        raise ValueError("factor_bounds must be positive and increasing")
    if not 0 < feasible_fraction < 1:
        raise ValueError("feasible_fraction must be strictly between zero and one")
    if not 0 < boundary_relative_tolerance < 1:
        raise ValueError(
            "boundary_relative_tolerance must be strictly between zero and one"
        )
    if search_iterations <= 0:
        raise ValueError("search_iterations must be positive")
    synthetic_case_kwargs.setdefault(
        "tail_execution_cycles",
        math.ceil(RECEIVING_PERIODS / EXECUTION_PERIODS),
    )

    from rolling_model import solve_full_horizon_packing_oracle

    seed = int(
        synthetic_case_kwargs.get("seed", 0)
        if oracle_seed is None
        else oracle_seed
    )
    cache: dict[float, tuple[dict, dict]] = {}
    evaluation_order: list[dict] = []

    def evaluate(factor: float) -> tuple[dict, dict]:
        normalized_factor = round(float(factor), 8)
        if normalized_factor in cache:
            return cache[normalized_factor]
        case = build_synthetic_rolling_case(
            ship_volume_factor=normalized_factor,
            **synthetic_case_kwargs,
        )
        certificate = solve_full_horizon_packing_oracle(
            case,
            release_basis="realized",
            time_limit=oracle_time_limit,
            threads=oracle_threads,
            seed=seed,
        )
        record = {
            "ship_volume_factor": normalized_factor,
            **certificate,
        }
        evaluation_order.append(record)
        cache[normalized_factor] = case, certificate
        return case, certificate

    lower_case, lower_certificate = evaluate(lower_factor)
    if lower_certificate["classification"] != "feasible":
        raise RuntimeError(
            "lower factor is not certified feasible; reduce factor_bounds[0]"
        )
    upper_case, upper_certificate = evaluate(upper_factor)
    if upper_certificate["classification"] != "overloaded":
        raise RuntimeError(
            "upper factor is not certified overloaded; increase factor_bounds[1]"
        )

    search_stopped_due_unknown = False
    for _iteration in range(search_iterations):
        relative_width = (
            upper_factor - lower_factor
        ) / max(lower_factor, 1e-9)
        if relative_width <= boundary_relative_tolerance:
            break
        midpoint = (lower_factor + upper_factor) / 2
        midpoint_case, midpoint_certificate = evaluate(midpoint)
        if midpoint_certificate["classification"] == "feasible":
            lower_factor = midpoint
            lower_case = midpoint_case
            lower_certificate = midpoint_certificate
        elif midpoint_certificate["classification"] == "overloaded":
            upper_factor = midpoint
            upper_case = midpoint_case
            upper_certificate = midpoint_certificate
        else:
            previous_bounds = lower_factor, upper_factor
            for probe in (
                (lower_factor + midpoint) / 2,
                (midpoint + upper_factor) / 2,
            ):
                probe_case, probe_certificate = evaluate(probe)
                if (
                    probe_certificate["classification"] == "feasible"
                    and probe > lower_factor
                ):
                    lower_factor = probe
                    lower_case = probe_case
                    lower_certificate = probe_certificate
                elif (
                    probe_certificate["classification"] == "overloaded"
                    and probe < upper_factor
                ):
                    upper_factor = probe
                    upper_case = probe_case
                    upper_certificate = probe_certificate
            if previous_bounds == (lower_factor, upper_factor):
                search_stopped_due_unknown = True
                break

    ordinary_factor = round(lower_factor * feasible_fraction, 8)
    ordinary_case, ordinary_certificate = evaluate(ordinary_factor)
    if ordinary_certificate["classification"] != "feasible":
        raise RuntimeError("ordinary factor unexpectedly lacks a feasible certificate")

    calibration = {
        "method": "full_horizon_integer_packing_volume_bisection",
        "feasible_fraction": feasible_fraction,
        "boundary_relative_tolerance": boundary_relative_tolerance,
        "certified_feasible_factor": lower_factor,
        "certified_overloaded_factor": upper_factor,
        "relative_boundary_width": (
            upper_factor - lower_factor
        ) / max(lower_factor, 1e-9),
        "boundary_tolerance_met": (
            (upper_factor - lower_factor) / max(lower_factor, 1e-9)
            <= boundary_relative_tolerance
        ),
        "search_stopped_due_unknown": search_stopped_due_unknown,
        "unknown_evaluation_count": sum(
            record["classification"] == "unknown"
            for record in evaluation_order
        ),
        "oracle_time_limit": oracle_time_limit,
        "evaluations": evaluation_order,
    }
    labeled = {
        "feasible": (ordinary_case, ordinary_certificate),
        "tight": (lower_case, lower_certificate),
        "overloaded": (upper_case, upper_certificate),
    }
    for label, (case, certificate) in labeled.items():
        case["oracle_case_class"] = label
        case["oracle_certificate"] = dict(certificate)
        case["oracle_calibration"] = {
            key: value for key, value in calibration.items() if key != "evaluations"
        }
    return {
        label: case for label, (case, _certificate) in labeled.items()
    } | {"calibration": calibration}


def aggregate_size_period_pressure_diagnostics(
    case: dict,
    *,
    release_basis: str = "realized",
) -> dict:
    """Measure full-horizon load against aggregate capacity by box size.

    This is an interpretable pressure diagnostic, not a packing-feasibility
    test: it deliberately ignores bay-level height compatibility and integer
    fragmentation.  Formal pressure cases therefore require a separate
    integer packing-oracle certificate after target calibration.
    """
    if release_basis not in {"realized", "planned"}:
        raise ValueError("release_basis must be 'realized' or 'planned'")
    release_key = (
        "realized_ship_release_period"
        if release_basis == "realized"
        else "planned_ship_release_period"
    )
    releases = case[release_key]
    attrs = case["group_attrs"]
    demand = {
        (ship, group, int(period)): int(quantity)
        for (ship, group, period), quantity in case["true_flow"].items()
        if int(quantity) > 0
    }
    sizes = sorted(
        set(case["bay_size"].values())
        | {attrs[group]["size"] for _ship, group, _period in demand}
    )
    capacity_by_size = {
        size: sum(
            int(case["capacity"][bay])
            for bay in case["bays"]
            if case["bay_size"][bay] == size
        )
        for size in sizes
    }
    if any(capacity <= 0 for capacity in capacity_by_size.values()):
        raise ValueError("every demanded size must have positive yard capacity")

    old_releases = case.get("old_release_period", {})
    last_arrival = max(
        (period for _ship, _group, period in demand),
        default=0,
    )
    peak_ratio = 0.0
    peak_record: dict[str, int | float | str] | None = None
    for period in range(last_arrival + 1):
        for size in sizes:
            locked_boxes = sum(
                int(quantity)
                for (bay, old_ship), quantity in case.get(
                    "locked_initial", {}
                ).items()
                if case["bay_size"][bay] == size
                and int(old_releases.get(old_ship, INF)) > period
            )
            active_new_boxes = sum(
                quantity
                for (ship, group, arrival), quantity in demand.items()
                if attrs[group]["size"] == size
                and arrival <= period < int(releases[ship])
            )
            capacity = capacity_by_size[size]
            ratio = (locked_boxes + active_new_boxes) / capacity
            if ratio > peak_ratio:
                peak_ratio = ratio
                peak_record = {
                    "period": period,
                    "size": size,
                    "locked_boxes": locked_boxes,
                    "active_new_boxes": active_new_boxes,
                    "capacity_boxes": capacity,
                    "load_ratio": ratio,
                }
    return {
        "metric": "peak_size_period_aggregate_capacity_load_ratio",
        "release_basis": release_basis,
        "peak_load_ratio": peak_ratio,
        "peak": peak_record,
        "capacity_by_size": capacity_by_size,
        "total_true_demand": sum(demand.values()),
    }


def build_integer_certified_pressure_case_family(
    *,
    pressure_targets: dict[str, float],
    factor_bounds: tuple[float, float] = (.01, 4.0),
    target_absolute_tolerance: float = .03,
    search_iterations: int = 14,
    oracle_time_limit: float = 60.0,
    oracle_threads: int = 1,
    oracle_seed: int | None = None,
    **synthetic_case_kwargs,
) -> dict:
    """Build pressure-targeted cases and certify exact integer packability.

    A cheap aggregate load ratio calibrates demand intensity.  It never
    substitutes for feasibility: each selected case must subsequently receive
    a zero-shortage certificate from the independent full-horizon integer
    bay-packing oracle.
    """
    if "ship_volume_factor" in synthetic_case_kwargs:
        raise ValueError(
            "ship_volume_factor is calibrated internally and must not be supplied"
        )
    if not pressure_targets:
        raise ValueError("pressure_targets must not be empty")
    if any(not 0 < float(target) < 1 for target in pressure_targets.values()):
        raise ValueError("pressure targets must be strictly between zero and one")
    if target_absolute_tolerance <= 0:
        raise ValueError("target_absolute_tolerance must be positive")
    if search_iterations <= 0:
        raise ValueError("search_iterations must be positive")
    lower_bound, upper_bound = map(float, factor_bounds)
    if lower_bound <= 0 or upper_bound <= lower_bound:
        raise ValueError("factor_bounds must be positive and increasing")
    synthetic_case_kwargs.setdefault(
        "tail_execution_cycles",
        math.ceil(RECEIVING_PERIODS / EXECUTION_PERIODS),
    )

    from rolling_model import solve_full_horizon_packing_oracle

    seed = int(
        synthetic_case_kwargs.get("seed", 0)
        if oracle_seed is None
        else oracle_seed
    )
    cache: dict[float, tuple[dict, dict]] = {}

    def evaluate(factor: float) -> tuple[dict, dict]:
        normalized = round(float(factor), 8)
        if normalized not in cache:
            case = build_synthetic_rolling_case(
                ship_volume_factor=normalized,
                **synthetic_case_kwargs,
            )
            cache[normalized] = (
                case,
                aggregate_size_period_pressure_diagnostics(case),
            )
        return cache[normalized]

    selected: dict[str, tuple[dict, dict, float]] = {}
    for label, raw_target in sorted(
        pressure_targets.items(),
        key=lambda item: item[1],
    ):
        target = float(raw_target)
        lower_factor = lower_bound
        upper_factor = upper_bound
        lower_case, lower_diagnostics = evaluate(lower_factor)
        upper_case, upper_diagnostics = evaluate(upper_factor)
        if (
            lower_diagnostics["peak_load_ratio"]
            > target + target_absolute_tolerance
        ):
            raise RuntimeError(
                f"target {target:g} is below unavoidable initial pressure"
            )
        if (
            upper_diagnostics["peak_load_ratio"]
            < target - target_absolute_tolerance
        ):
            raise RuntimeError(
                f"target {target:g} exceeds the supplied factor range"
            )

        candidates = [
            (lower_case, lower_diagnostics, lower_factor),
            (upper_case, upper_diagnostics, upper_factor),
        ]
        for _iteration in range(search_iterations):
            midpoint = (lower_factor + upper_factor) / 2
            midpoint_case, midpoint_diagnostics = evaluate(midpoint)
            candidates.append(
                (midpoint_case, midpoint_diagnostics, midpoint)
            )
            midpoint_ratio = midpoint_diagnostics["peak_load_ratio"]
            if abs(midpoint_ratio - target) <= target_absolute_tolerance:
                break
            if midpoint_ratio < target:
                lower_factor = midpoint
            else:
                upper_factor = midpoint

        best_case, best_diagnostics, best_factor = min(
            candidates,
            key=lambda item: (
                abs(item[1]["peak_load_ratio"] - target),
                item[2],
            ),
        )
        error = abs(best_diagnostics["peak_load_ratio"] - target)
        if error > target_absolute_tolerance:
            raise RuntimeError(
                f"could not calibrate {label} pressure target {target:g}; "
                f"best absolute error={error:g}"
            )
        selected[label] = (
            best_case,
            best_diagnostics,
            best_factor,
        )

    labeled: dict[str, dict] = {}
    for label, (case, diagnostics, factor) in selected.items():
        certificate = solve_full_horizon_packing_oracle(
            case,
            release_basis="realized",
            time_limit=oracle_time_limit,
            threads=oracle_threads,
            seed=seed,
        )
        if certificate["classification"] != "feasible":
            raise RuntimeError(
                f"{label} pressure case lacks a zero-shortage integer "
                f"packing certificate: {certificate['classification']}"
            )
        target = float(pressure_targets[label])
        case["capacity_pressure_profile"] = label
        case["capacity_pressure_target"] = target
        case["capacity_pressure_diagnostics"] = diagnostics
        case["oracle_case_class"] = "feasible"
        case["oracle_certificate"] = dict(certificate)
        case["oracle_calibration"] = {
            "method": (
                "aggregate_size_period_pressure_target_then_integer_packing"
            ),
            "target_peak_load_ratio": target,
            "actual_peak_load_ratio": diagnostics["peak_load_ratio"],
            "target_absolute_error": abs(
                diagnostics["peak_load_ratio"] - target
            ),
            "target_absolute_tolerance": target_absolute_tolerance,
            "ship_volume_factor": factor,
            "factor_bounds": factor_bounds,
            "search_iterations": search_iterations,
            "integer_oracle_time_limit": oracle_time_limit,
        }
        labeled[label] = case
    return labeled


def build_repair_pressure_case(*, level: str = "nearby", seed: int = 0) -> dict:
    """Create a small deterministic case that exercises progressive repair."""
    if level not in ("nearby", "global"):
        raise ValueError("level must be nearby or global")
    case = build_synthetic_rolling_case(
        seed=seed,
        num_blocks=8,
        bays_per_block=4,
        num_ships=4,
        cycles=2,
        active_ship_overlap=3,
        pod_count=4,
        initial_utilization=0,
        forecast_error=.20,
        forecast_error_mode="mixed",
        containers_per_ship_range=(60, 60),
    )
    factor = 3
    case["forecasts"] = {
        key: value * factor for key, value in case["forecasts"].items()
    }
    shock_candidates = {
        group: sum(
            value
            for (cycle, ship, g, _period), value in case["forecasts"].items()
            if cycle == 1 and ship == "V01" and g == group
        )
        for cycle, ship, group, _period in case["forecasts"]
        if cycle == 1 and ship == "V01"
    }
    shock_group = min(shock_candidates, key=lambda group: (shock_candidates[group], group))
    shock_keys = sorted(
        key
        for key in case["forecasts"]
        if key[0] == 1 and key[1] == "V01" and key[2] == shock_group
    )
    shock_total = 210 if level == "nearby" else 540
    shock_profile = _integer_profile(
        shock_total,
        [case["forecasts"][key] for key in shock_keys],
    )
    for key, value in zip(shock_keys, shock_profile):
        case["forecasts"][key] = value
    case["pressure_level"] = level
    case["pressure_demand_factor"] = factor
    case["pressure_shock_group"] = shock_group
    case["pressure_shock_total"] = shock_total
    return case


def initial_simulation_state(case: dict) -> dict:
    return {
        "cycle": 0,
        "actual_inventory": {},
        "previous_reservation": {},
        "previous_din": {},
        "locked_inventory": dict(case["locked_initial"]),
        "locked_height": dict(case["locked_height_initial"]),
        "completed": set(),
        "unplaced_actual": 0,
    }


def _participating_ships(case: dict, now: int, completed: set[str]) -> set[str]:
    return {
        ship
        for ship in case["ships"]
        if case["receiving_start_period"][ship] <= now < case["eta_period"][ship]
        and ship not in completed
    }


def _visible_ship_outbound_total(
    case: dict,
    state: dict,
    cycle: int,
    ship: str,
) -> int:
    """Return current inventory plus not-yet-due forecast arrivals."""
    now = cycle * case["execution_periods"]
    actual_total = sum(
        quantity
        for (_bay, j, _group), quantity in state["actual_inventory"].items()
        if j == ship
    )
    remaining_forecast = sum(
        quantity
        for (r, j, _group, absolute), quantity in case["forecasts"].items()
        if r == cycle and j == ship and absolute >= now
    )
    return actual_total + remaining_forecast


def build_visible_ship_outbound_forecast(
    case: dict,
    state: dict,
    cycle: int,
    ship: str,
    *,
    horizon_end: int | None = None,
) -> dict[int, int]:
    """Build and truncate a planned outbound profile using visible information."""
    now = cycle * case["execution_periods"]
    visible_total = _visible_ship_outbound_total(case, state, cycle, ship)
    planned_release = case["planned_ship_release_period"][ship]
    full_periods = list(range(case["eta_period"][ship], planned_release))
    if not full_periods or visible_total <= 0:
        return {}
    full_quantities = _integer_profile(visible_total, [1.0] * len(full_periods))
    full_profile = dict(zip(full_periods, full_quantities))
    lower = now
    upper = min(
        horizon_end if horizon_end is not None else planned_release,
        planned_release,
    )
    return {
        absolute: quantity
        for absolute, quantity in full_profile.items()
        if lower <= absolute < upper and quantity > 0
    }


def visible_ship_block_basis(
    case: dict,
    state: dict,
    previous_reservation: dict,
    ship: str,
) -> dict[str, int]:
    """Return the optimizer-visible block basis for planned outbound workload."""
    return {
        block: sum(
            quantity
            for (bay, j, _group), quantity in state["actual_inventory"].items()
            if j == ship and case["bay_block"][bay] == block and quantity > 0
        )
        + sum(
            quantity
            for (bay, j, _group), quantity in previous_reservation.items()
            if j == ship and case["bay_block"][bay] == block and quantity > 0
        )
        for block in case["blocks"]
    }


def optimization_snapshot(case: dict, state: dict) -> dict:
    """Build the optimizer-visible snapshot without exposing hidden realization data."""
    cycle = state["cycle"]
    now = cycle * case["execution_periods"]
    end = now + case["lookahead_periods"]
    active: list[str] = []
    new: list[str] = []
    continuing: list[str] = []
    for ship in case["ships"]:
        start = case["receiving_start_period"][ship]
        if now < start <= now + case["execution_periods"]:
            new.append(ship)
            active.append(ship)
        elif start <= now < case["eta_period"][ship] and ship not in state["completed"]:
            continuing.append(ship)
            active.append(ship)
    active_set = set(active)
    outbound_relevant_ships = {
        ship
        for ship in case["ships"]
        if case["eta_period"][ship] < end
        and case["planned_ship_release_period"][ship] > now
    }
    previous_reservation = {
        key: quantity
        for key, quantity in state["previous_reservation"].items()
        if key[1] in active_set and quantity > 0
    }
    previous_din = {
        key: quantity
        for key, quantity in state.get("previous_din", {}).items()
        if key[1] in active_set and key[3] >= 0 and quantity > 0
    }
    forecast: dict[tuple[str, str, int], int] = {}
    for ship in active:
        for group in case["group_attrs"]:
            for absolute in range(now, end):
                quantity = case["forecasts"].get((cycle, ship, group, absolute), 0)
                if quantity:
                    forecast[ship, group, absolute - now] = quantity

    outbound: dict[tuple[str, int], int] = {}
    planned_ship_set = set(case["ships"])
    for block in case["blocks"]:
        for absolute in range(now, end):
            quantity = sum(
                value
                for (r, _old, k, period), value in case["outbound_forecasts"].items()
                if r == cycle
                and _old not in planned_ship_set
                and k == block
                and period == absolute
            )
            if quantity:
                outbound[block, absolute - now] = quantity
    visible_outbound_total_by_ship: dict[str, int] = {}
    remaining_outbound_total_by_ship: dict[str, int] = {}
    for ship in sorted(outbound_relevant_ships):
        block_basis = visible_ship_block_basis(
            case,
            state,
            state.get("previous_reservation", {}),
            ship,
        )
        if not sum(block_basis.values()):
            closest = min(case["blocks"], key=lambda block: case["distance"][ship, block])
            block_basis[closest] = 1
        visible_outbound = build_visible_ship_outbound_forecast(
            case,
            state,
            cycle,
            ship,
            horizon_end=end,
        )
        visible_total = _visible_ship_outbound_total(case, state, cycle, ship)
        if visible_total > 0:
            visible_outbound_total_by_ship[ship] = visible_total
        remaining_total = sum(visible_outbound.values())
        if remaining_total > 0:
            remaining_outbound_total_by_ship[ship] = remaining_total
        for absolute, quantity in sorted(visible_outbound.items()):
            if not quantity:
                continue
            distributed = _integer_profile(
                quantity, [block_basis[block] for block in case["blocks"]]
            )
            for block, value in zip(case["blocks"], distributed):
                if value:
                    key = (block, absolute - now)
                    outbound[key] = outbound.get(key, 0) + value

    remaining = {
        (ship, group): sum(
            quantity
            for (j, g, _period), quantity in forecast.items()
            if j == ship and g == group
        )
        for ship in active
        for group in case["group_attrs"]
    }
    remaining = {pair: quantity for pair, quantity in remaining.items() if quantity > 0}
    maximum_forecast_lead_sigma = max(
        (
            max(
                FORECAST_MIN_SIGMA_RATIO,
                min(1.0, period / max(1, case["receiving_periods"])),
            )
            for (_ship, _group, period), quantity in forecast.items()
            if quantity > 0
        ),
        default=0.0,
    )
    forecast_uncertainty_buffer = (
        float(case.get("forecast_error", 0.0))
        * maximum_forecast_lead_sigma
    )
    locked_release = {
        (bay, old_ship): case["old_release_period"].get(old_ship, INF) - now
        for bay, old_ship in state["locked_inventory"]
    }
    planned_ships = (
        set(case["ships"])
        | {ship for _bay, ship, _group in state["actual_inventory"]}
        | {ship for _bay, ship, _group in previous_reservation}
        | set(active)
    )
    ship_release_local = {
        ship: case["planned_ship_release_period"].get(ship, INF) - now
        for ship in sorted(planned_ships)
    }
    base_keys = (
        "blocks",
        "bays",
        "bay_block",
        "bays_in_block",
        "bay_size",
        "capacity",
        "heights",
        "group_attrs",
        "distance",
        "period_hours",
        "execution_periods",
        "lookahead_periods",
    )
    snapshot = {key: case[key] for key in base_keys} | {
        "cycle": cycle,
        "absolute_start_period": now,
        "periods": list(range(case["lookahead_periods"])),
        "active_ships": active,
        "new_ships": new,
        "continuing_ships": continuing,
        "outbound_relevant_ships": sorted(outbound_relevant_ships),
        "outbound_forecast_diagnostics": {
            "outbound_relevant_ships": sorted(outbound_relevant_ships),
            "loading_phase_ships": sorted(
                ship
                for ship in outbound_relevant_ships
                if case["eta_period"][ship] <= now
                < case["planned_ship_release_period"][ship]
            ),
            "receiving_phase_outbound_ships": sorted(
                ship
                for ship in outbound_relevant_ships
                if now < case["eta_period"][ship] < end
            ),
            "visible_outbound_total_by_ship": visible_outbound_total_by_ship,
            "remaining_outbound_total_by_ship": remaining_outbound_total_by_ship,
        },
        "actual_inventory": dict(state["actual_inventory"]),
        "previous_reservation": previous_reservation,
        "previous_din": previous_din,
        "locked_inventory": dict(state["locked_inventory"]),
        "locked_height": dict(state["locked_height"]),
        "locked_release_local": locked_release,
        "ship_release_local": ship_release_local,
        "forecast_arrivals": forecast,
        "forecast_uncertainty_buffer": forecast_uncertainty_buffer,
        "forecast_uncertainty_base_error": float(
            case.get("forecast_error", 0.0)
        ),
        "forecast_uncertainty_lead_sigma": maximum_forecast_lead_sigma,
        "forecast_uncertainty_basis": (
            "declared_error_times_max_visible_forecast_lead_sigma"
        ),
        "forecast_outbound": outbound,
        "remaining_demand": remaining,
        "release_period_basis": case["release_period_basis"],
    }
    from rolling_model import validate_snapshot_temporal_consistency

    validate_snapshot_temporal_consistency(snapshot)
    return snapshot


def _realized_present(case: dict, ship: str, absolute_period: int) -> bool:
    return case["realized_ship_release_period"].get(ship, INF) > absolute_period


def _free_capacity(
    case: dict,
    state: dict,
    actual_inventory: dict,
    bay: str,
    absolute_period: int,
) -> int:
    locked = sum(
        quantity
        for (i, old_ship), quantity in state["locked_inventory"].items()
        if i == bay and case["old_release_period"].get(old_ship, INF) > absolute_period
    )
    actual = sum(
        quantity
        for (i, ship, _group), quantity in actual_inventory.items()
        if i == bay and _realized_present(case, ship, absolute_period)
    )
    return max(0, int(case["capacity"][bay] - locked - actual))


def feasible_take(
    case: dict,
    state: dict,
    actual_inventory: dict,
    reserve: dict,
    bay: str,
    ship: str,
    group: str,
    absolute_period: int,
    requested_quantity: int,
) -> int:
    """Return the truly feasible quantity for either planned or fallback placement."""
    if requested_quantity <= 0 or not _realized_present(case, ship, absolute_period):
        return 0
    if case["bay_size"].get(bay) != case["group_attrs"][group]["size"]:
        return 0
    reservation = max(0, int(round(reserve.get((bay, ship, group), 0))))
    if reservation <= 0:
        return 0
    existing_heights = {
        case["group_attrs"][g]["height"]
        for (i, j, g), quantity in actual_inventory.items()
        if i == bay
        and quantity > 0
        and _realized_present(case, j, absolute_period)
    } | {
        height
        for (i, old_ship), height in state["locked_height"].items()
        if i == bay and case["old_release_period"].get(old_ship, INF) > absolute_period
    }
    if existing_heights and case["group_attrs"][group]["height"] not in existing_heights:
        return 0
    return min(
        int(requested_quantity),
        reservation,
        _free_capacity(case, state, actual_inventory, bay, absolute_period),
    )


def validate_execution_state(case: dict, state: dict, absolute_period: int) -> dict:
    """Validate realized bay capacity, size, height, releases, and nonnegativity."""
    violations: dict[str, float] = {}

    def record(name: str, value: float) -> None:
        violations[name] = max(violations.get(name, 0.0), max(0.0, float(value)))

    actual = state.get("actual_inventory", {})
    reserve = state.get("remaining_reservation", {})
    for bay in case["bays"]:
        locked = sum(
            quantity
            for (i, old_ship), quantity in state.get("locked_inventory", {}).items()
            if i == bay and case["old_release_period"].get(old_ship, INF) > absolute_period
        )
        live = sum(
            quantity
            for (i, ship, _group), quantity in actual.items()
            if i == bay and _realized_present(case, ship, absolute_period)
        )
        record("capacity", locked + live - case["capacity"][bay])
        heights = {
            case["group_attrs"][group]["height"]
            for (i, ship, group), quantity in actual.items()
            if i == bay and quantity > 0 and _realized_present(case, ship, absolute_period)
        } | {
            height
            for (i, old_ship), height in state.get("locked_height", {}).items()
            if i == bay and case["old_release_period"].get(old_ship, INF) > absolute_period
        }
        record("height", len(heights) - 1)
    for (bay, ship, group), quantity in actual.items():
        record("inventory_nonnegative", -quantity)
        record("size", int(case["bay_size"][bay] != case["group_attrs"][group]["size"]))
        if quantity > 0:
            record("released_inventory", int(not _realized_present(case, ship, absolute_period)))
    for (_bay, old_ship), quantity in state.get("locked_inventory", {}).items():
        record("locked_inventory_nonnegative", -quantity)
        if quantity > 0:
            record(
                "released_locked_inventory",
                int(case["old_release_period"].get(old_ship, INF) <= absolute_period),
            )
    for quantity in reserve.values():
        record("reservation_nonnegative", -quantity)
    maximum = max(violations.values(), default=0.0)
    return {"feasible": maximum <= 1e-6, "max_violation": maximum, "violations": violations}


def _realized_outbound(
    case: dict,
    actual_inventory: dict,
    absolute_period: int,
) -> dict[str, int]:
    outbound = {
        block: sum(
            quantity
            for (_old, k, period), quantity in case["old_outbound_flow"].items()
            if k == block and period == absolute_period
        )
        for block in case["blocks"]
    }
    for ship in case["ships"]:
        quantity = case["ship_outbound_flow"].get((ship, absolute_period), 0)
        if not quantity:
            continue
        basis = {
            block: sum(
                value
                for (bay, j, _group), value in actual_inventory.items()
                if j == ship and case["bay_block"][bay] == block
            )
            for block in case["blocks"]
        }
        if not sum(basis.values()):
            closest = min(case["blocks"], key=lambda block: case["distance"][ship, block])
            basis[closest] = 1
        for block, value in zip(
            case["blocks"],
            _integer_profile(quantity, [basis[block] for block in case["blocks"]]),
        ):
            outbound[block] += value
    return outbound


def _realized_space_metrics(case: dict, state: dict, absolute_period: int) -> dict:
    actual = state["actual_inventory"]
    support = {
        (ship, case["group_attrs"][group]["pod"], bay)
        for (bay, ship, group), quantity in actual.items()
        if quantity > 0 and _realized_present(case, ship, absolute_period)
    }
    pair_bays: dict[tuple[str, str], set[str]] = {}
    for ship, pod, bay in support:
        pair_bays.setdefault((ship, pod), set()).add(bay)
    bay_counts = [len(values) for values in pair_bays.values()]
    utilizations = []
    for block in case["blocks"]:
        block_capacity = sum(case["capacity"][bay] for bay in case["bays_in_block"][block])
        occupancy = sum(
            quantity
            for (bay, old_ship), quantity in state["locked_inventory"].items()
            if case["bay_block"][bay] == block
            and case["old_release_period"].get(old_ship, INF) > absolute_period
        ) + sum(
            quantity
            for (bay, ship, _group), quantity in actual.items()
            if case["bay_block"][bay] == block
            and _realized_present(case, ship, absolute_period)
        )
        utilizations.append(occupancy / max(1, block_capacity))
    average = sum(utilizations) / max(1, len(utilizations))
    return {
        "support": support,
        "realized_active_ship_pod_bay_support": len(support),
        "realized_ship_pod_bay_count_sum": sum(bay_counts),
        "realized_ship_pod_observation_count": len(bay_counts),
        "realized_average_bays_per_ship_pod": (
            sum(bay_counts) / len(bay_counts) if bay_counts else 0.0
        ),
        "realized_max_bays_per_ship_pod": max(bay_counts, default=0),
        "realized_peak_block_utilization": max(utilizations, default=0.0),
        "realized_mean_absolute_utilization_deviation": (
            sum(abs(value - average) for value in utilizations) / max(1, len(utilizations))
        ),
        "realized_max_utilization_spread": (
            max(utilizations, default=0.0) - min(utilizations, default=0.0)
        ),
    }


def summarize_period_space_metrics(
    period_spaces: list[dict],
    initial_support: set[tuple[str, str, str]] | None = None,
) -> dict:
    """Aggregate true within-cycle peaks, activations, and weighted concentration."""
    previous_support = set(initial_support or ())
    activations = 0
    for space in period_spaces:
        current = set(space.get("support", ()))
        activations += len(current - previous_support)
        previous_support = current
    bay_count_sum = sum(
        space["realized_ship_pod_bay_count_sum"] for space in period_spaces
    )
    observation_count = sum(
        space["realized_ship_pod_observation_count"] for space in period_spaces
    )
    return {
        "realized_peak_block_utilization": max(
            (space["realized_peak_block_utilization"] for space in period_spaces),
            default=0.0,
        ),
        "realized_mean_absolute_utilization_deviation": (
            sum(
                space["realized_mean_absolute_utilization_deviation"]
                for space in period_spaces
            ) / max(1, len(period_spaces))
        ),
        "realized_max_utilization_spread": max(
            (space["realized_max_utilization_spread"] for space in period_spaces),
            default=0.0,
        ),
        "realized_support_activation_count": activations,
        "realized_ship_pod_bay_count_sum": bay_count_sum,
        "realized_ship_pod_observation_count": observation_count,
        "realized_average_bays_per_ship_pod": (
            bay_count_sum / observation_count if observation_count else 0.0
        ),
        "realized_max_bays_per_ship_pod": max(
            (space["realized_max_bays_per_ship_pod"] for space in period_spaces),
            default=0,
        ),
    }


def advance_state(case: dict, state: dict, solution: dict) -> tuple[dict, dict]:
    """Execute one non-overlapping 24-hour window with deterministic recourse."""
    cycle = state["cycle"]
    now = cycle * case["execution_periods"]
    actual = {
        key: quantity
        for key, quantity in state["actual_inventory"].items()
        if _realized_present(case, key[1], now)
    }
    locked = dict(state["locked_inventory"])
    locked_height = dict(state["locked_height"])
    reserve = {
        key: int(round(quantity))
        for key, quantity in solution.get("reservation", {}).items()
    }
    din = solution.get("din", {})
    cumulative_unplaced = state.get("unplaced_actual", 0)
    start_support = _realized_space_metrics(
        case,
        {**state, "actual_inventory": actual},
        now,
    )["support"]
    metrics = {
        "realized_arrivals": 0,
        "planned_placement_quantity": 0,
        "planned_infeasible_quantity": 0,
        "fallback_placement_quantity": 0,
        "fallback_candidate_attempts": 0,
        "fallback_success_quantity": 0,
        "realized_unplaced": 0,
        "realized_distance": 0.0,
        "realized_in_out_conflict": 0.0,
    }
    period_spaces: list[dict] = []

    for local in range(case["execution_periods"]):
        absolute = now + local
        actual = {
            key: quantity
            for key, quantity in actual.items()
            if _realized_present(case, key[1], absolute)
        }
        locked = {
            key: quantity
            for key, quantity in locked.items()
            if case["old_release_period"].get(key[1], INF) > absolute
        }
        locked_height = {key: height for key, height in locked_height.items() if key in locked}
        execution_state = {
            "actual_inventory": actual,
            "locked_inventory": locked,
            "locked_height": locked_height,
            "remaining_reservation": reserve,
        }
        realized_outbound = _realized_outbound(case, actual, absolute)
        outbound_peak = max(realized_outbound.values(), default=1)

        for (ship, group, period), realized in sorted(case["true_flow"].items()):
            if period != absolute or realized <= 0:
                continue
            metrics["realized_arrivals"] += realized
            planned_entries = sorted(
                (
                    (int(round(din.get((bay, ship, group, local), 0))), bay)
                    for bay in case["bays"]
                    if din.get((bay, ship, group, local), 0) > 0
                ),
                key=lambda item: (-item[0], item[1]),
            )
            planned_blocks = {case["bay_block"][bay] for _quantity, bay in planned_entries}
            left = realized
            for planned_quantity, bay in planned_entries:
                requested = min(left, planned_quantity)
                take = feasible_take(
                    case,
                    execution_state,
                    actual,
                    reserve,
                    bay,
                    ship,
                    group,
                    absolute,
                    requested,
                )
                metrics["planned_infeasible_quantity"] += requested - take
                if take:
                    key = (bay, ship, group)
                    actual[key] = actual.get(key, 0) + take
                    reserve[key] -= take
                    left -= take
                    block = case["bay_block"][bay]
                    metrics["planned_placement_quantity"] += take
                    metrics["realized_distance"] += take * case["distance"][ship, block]
                    metrics["realized_in_out_conflict"] += (
                        take * realized_outbound.get(block, 0) / max(1, outbound_peak)
                    )
                if left <= 0:
                    break

            if left > 0:
                pod = case["group_attrs"][group]["pod"]
                support = {
                    (j, case["group_attrs"][g]["pod"], bay)
                    for (bay, j, g), quantity in actual.items()
                    if quantity > 0 and _realized_present(case, j, absolute)
                }
                candidates = []
                for (bay, j, g), quantity in reserve.items():
                    if j != ship or g != group or quantity <= 0:
                        continue
                    block = case["bay_block"][bay]
                    candidates.append((
                        (
                            int(bool(planned_blocks) and block not in planned_blocks),
                            int((ship, pod, bay) not in support),
                            realized_outbound.get(block, 0) / max(1, outbound_peak),
                            case["distance"][ship, block],
                            -_free_capacity(case, execution_state, actual, bay, absolute),
                            -quantity,
                            bay,
                        ),
                        bay,
                    ))
                for _ranking, bay in sorted(candidates):
                    if left <= 0:
                        break
                    metrics["fallback_candidate_attempts"] += 1
                    take = feasible_take(
                        case,
                        execution_state,
                        actual,
                        reserve,
                        bay,
                        ship,
                        group,
                        absolute,
                        left,
                    )
                    if not take:
                        continue
                    key = (bay, ship, group)
                    actual[key] = actual.get(key, 0) + take
                    reserve[key] -= take
                    left -= take
                    block = case["bay_block"][bay]
                    metrics["fallback_placement_quantity"] += take
                    metrics["fallback_success_quantity"] += take
                    metrics["realized_distance"] += take * case["distance"][ship, block]
                    metrics["realized_in_out_conflict"] += (
                        take * realized_outbound.get(block, 0) / max(1, outbound_peak)
                    )
            cumulative_unplaced += left
            metrics["realized_unplaced"] += left

        if VALIDATE_EACH_EXECUTION_PERIOD:
            execution_state["actual_inventory"] = actual
            report = validate_execution_state(case, execution_state, absolute)
            if not report["feasible"]:
                raise RuntimeError(f"execution state infeasible at period {absolute}: {report}")
        period_space = _realized_space_metrics(
            case,
            {
                "actual_inventory": actual,
                "locked_inventory": locked,
            },
            absolute,
        )
        period_spaces.append(period_space)

    next_cycle = cycle + 1
    boundary = next_cycle * case["execution_periods"]
    actual = {
        key: quantity
        for key, quantity in actual.items()
        if _realized_present(case, key[1], boundary)
    }
    locked = {
        key: quantity
        for key, quantity in locked.items()
        if case["old_release_period"].get(key[1], INF) > boundary
    }
    locked_height = {key: height for key, height in locked_height.items() if key in locked}
    next_active = _participating_ships(case, boundary, state["completed"])
    next_previous = {
        key: quantity
        for key, quantity in reserve.items()
        if key[1] in next_active and quantity > 0
    }
    next_din = {
        (bay, ship, group, period - case["execution_periods"]): int(round(quantity))
        for (bay, ship, group, period), quantity in din.items()
        if ship in next_active
        and period >= case["execution_periods"]
        and quantity > 0
    }
    completed = set(state["completed"])
    for ship in case["ships"]:
        if boundary >= case["eta_period"][ship]:
            completed.add(ship)
    next_state = {
        "cycle": next_cycle,
        "actual_inventory": actual,
        "previous_reservation": next_previous,
        "previous_din": next_din,
        "locked_inventory": locked,
        "locked_height": locked_height,
        "completed": completed,
        "unplaced_actual": cumulative_unplaced,
    }
    metrics.update(summarize_period_space_metrics(period_spaces, start_support))
    metrics["fallback_rate"] = (
        metrics["fallback_placement_quantity"] / metrics["realized_arrivals"]
        if metrics["realized_arrivals"] else 0.0
    )
    metrics["unplaced_rate"] = (
        metrics["realized_unplaced"] / metrics["realized_arrivals"]
        if metrics["realized_arrivals"] else 0.0
    )
    final_report = validate_execution_state(
        case,
        {**next_state, "remaining_reservation": next_previous},
        boundary,
    )
    if not final_report["feasible"]:
        raise RuntimeError(f"cycle-end execution state infeasible: {final_report}")
    metrics["execution_validation"] = final_report
    return next_state, metrics

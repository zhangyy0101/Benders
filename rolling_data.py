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
    FORECAST_ERROR_MODES,
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


def _forecast_cycle(
    *,
    seed: int,
    cycle: int,
    mode: str,
    error: float,
    ships: list[str],
    groups: list[str],
    booking_flow: dict,
    receiving_start: dict[str, int],
    eta_period: dict[str, int],
) -> dict[tuple[str, str, int], int]:
    """Create a forecast from a public booking baseline, never from hidden truth."""
    rng = random.Random(seed * 100_003 + cycle * 9_973 + 17)
    now = cycle * EXECUTION_PERIODS
    result: dict[tuple[str, str, int], int] = {}
    ship_factor = {
        ship: max(0.0, 1.0 + rng.gauss(0, error)) for ship in ships
    }
    booking_factor: dict[tuple[str, str], float] = {}
    if mode in ("booking_add_cancel", "mixed"):
        for ship in ships:
            for group in groups:
                draw = rng.random()
                if draw < error * 0.20:
                    booking_factor[ship, group] = 0.0
                else:
                    booking_factor[ship, group] = max(0.0, 1.0 + rng.gauss(0, error))

    for (ship, group, absolute), booked in sorted(booking_flow.items()):
        if absolute < now:
            continue
        target_period = absolute
        if mode in ("timing_shift", "mixed") and rng.random() < error:
            target_period += -1 if rng.random() < 0.5 else 1
            target_period = min(
                eta_period[ship] - 1,
                max(receiving_start[ship], target_period),
            )
        factor = 1.0
        if mode in ("multiplicative", "mixed"):
            lead = max(1, absolute - now)
            sigma = error * min(1.0, lead / RECEIVING_PERIODS)
            factor *= max(0.0, 1.0 + rng.gauss(0, sigma))
        if mode in ("ship_correlated", "mixed"):
            factor *= ship_factor[ship]
        if mode in ("booking_add_cancel", "mixed"):
            factor *= booking_factor[ship, group]
        quantity = max(0, int(round(booked * factor)))
        if quantity and target_period >= now:
            key = (ship, group, target_period)
            result[key] = result.get(key, 0) + quantity

    if mode in ("booking_add_cancel", "mixed") and error > 0:
        positive_pairs = {(ship, group) for ship, group, _period in booking_flow}
        for ship in ships:
            zero_groups = [group for group in groups if (ship, group) not in positive_pairs]
            if not zero_groups or rng.random() >= min(0.75, error * 2):
                continue
            group = zero_groups[rng.randrange(len(zero_groups))]
            added = max(1, int(round(20 * error)))
            profile = _integer_profile(added, [1, 2, 3, 3, 2, 1])
            start = receiving_start[ship] + 3
            for offset, quantity in enumerate(profile):
                absolute = min(eta_period[ship] - 1, start + offset)
                if quantity and absolute >= now:
                    key = (ship, group, absolute)
                    result[key] = result.get(key, 0) + quantity
    return result


def build_synthetic_rolling_case(
    *,
    seed: int = 0,
    num_blocks: int = 8,
    bays_per_block: int = 8,
    num_ships: int = 8,
    cycles: int = 6,
    bay_capacity: int = 50,
    initial_utilization: float = .25,
    forecast_error: float = .10,
    forecast_error_mode: str = "multiplicative",
    outbound_boxes_per_period: int = DEFAULT_OUTBOUND_BOXES_PER_6H,
    containers_per_ship_range: tuple[int, int] = (60, 160),
    active_ship_overlap: int = 2,
    pod_count: int = 3,
    ship_operation_duration_periods: int | tuple[int, int] | None = None,
    release_delay_periods: int | dict[str, int] = 0,
) -> dict:
    """Build a reproducible case with external ship schedules and hidden truth."""
    if outbound_boxes_per_period <= 0:
        raise ValueError("outbound_boxes_per_period must be positive")
    if forecast_error_mode not in FORECAST_ERROR_MODES:
        raise ValueError(f"forecast_error_mode must be one of {FORECAST_ERROR_MODES}")
    if not 0 <= initial_utilization <= 1:
        raise ValueError("initial_utilization must be between zero and one")
    if active_ship_overlap <= 0 or pod_count <= 0:
        raise ValueError("active_ship_overlap and pod_count must be positive")
    low_boxes, high_boxes = containers_per_ship_range
    if low_boxes <= 0 or high_boxes < low_boxes:
        raise ValueError("containers_per_ship_range must be positive and ordered")

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
        operation_duration[ship] = duration
        planned_release[ship] = eta_period[ship] + duration
        delay = (
            release_delay_periods.get(ship, 0)
            if isinstance(release_delay_periods, dict)
            else release_delay_periods
        )
        realized_release[ship] = planned_release[ship] + max(0, int(delay))
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
        ship_total = rng.randint(low_boxes, high_boxes)
        group_quantities = _integer_profile(
            ship_total, [rng.uniform(.5, 1.5) for _group in selected]
        )
        for group, total in zip(selected, group_quantities):
            if total <= 0:
                continue
            for offset, quantity in enumerate(_integer_profile(total, triangle)):
                if quantity:
                    booking_flow[ship, group, start + offset] = quantity

    # The simulator realization and every forecast are independent draws from the
    # same public booking baseline.  Thus zero error remains a deliberate perfect-
    # forecast scenario, while the forecast generator never reads hidden truth.
    true_flow = _forecast_cycle(
        seed=seed + 91_919,
        cycle=0,
        mode=forecast_error_mode,
        error=forecast_error,
        ships=ships,
        groups=groups,
        booking_flow=booking_flow,
        receiving_start=receiving_start,
        eta_period=eta_period,
    )
    true_total: dict[tuple[str, str], int] = {}
    for (ship, group, _absolute), quantity in true_flow.items():
        true_total[ship, group] = true_total.get((ship, group), 0) + quantity

    forecasts: dict[tuple[int, str, str, int], int] = {}
    for cycle in range(cycles):
        cycle_forecast = _forecast_cycle(
            seed=seed,
            cycle=cycle,
            mode=forecast_error_mode,
            error=forecast_error,
            ships=ships,
            groups=groups,
            booking_flow=booking_flow,
            receiving_start=receiving_start,
            eta_period=eta_period,
        )
        for (ship, group, absolute), quantity in cycle_forecast.items():
            forecasts[cycle, ship, group, absolute] = quantity

    locked: dict[tuple[str, str], int] = {}
    locked_height: dict[tuple[str, str], str] = {}
    old_release_period: dict[str, int] = {}
    target = int(sum(capacity.values()) * initial_utilization)
    placed = 0
    old_count = max(2, num_blocks // 3)
    for old_index in range(old_count):
        old_ship = f"OLD{old_index + 1:02d}"
        quota = math.ceil(target / old_count) if old_count else 0
        ship_placed = 0
        for bay in bays[old_index::old_count]:
            if placed >= target or ship_placed >= quota:
                break
            quantity = min(
                capacity[bay] // 2,
                target - placed,
                quota - ship_placed,
            )
            if quantity <= 0:
                continue
            locked[bay, old_ship] = quantity
            locked_height[bay, old_ship] = heights[(bays.index(bay) // 2) % 2]
            placed += quantity
            ship_placed += quantity

    old_outbound: dict[tuple[str, str, int], int] = {}
    for old_index, old_ship in enumerate(sorted({ship for _bay, ship in locked})):
        total = sum(quantity for (_bay, ship), quantity in locked.items() if ship == old_ship)
        duration = max(1, math.ceil(total / outbound_boxes_per_period))
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
    ship_outbound_forecasts: dict[tuple[int, str, int], int] = {}
    for cycle in range(cycles):
        now = cycle * EXECUTION_PERIODS
        for (old_ship, block, absolute), truth in old_outbound.items():
            if absolute >= now:
                outbound_forecasts[cycle, old_ship, block, absolute] = truth
        for ship in ships:
            visible_total = sum(
                quantity
                for (r, j, _group, _absolute), quantity in forecasts.items()
                if r == cycle and j == ship
            )
            duration = max(1, planned_release[ship] - eta_period[ship])
            for offset, quantity in enumerate(
                _integer_profile(visible_total, [1] * duration)
            ):
                absolute = eta_period[ship] + offset
                if quantity and absolute >= now:
                    ship_outbound_forecasts[cycle, ship, absolute] = quantity

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
        "forecast_generation_basis": "public_booking_baseline",
        "forecasts": forecasts,
        "distance": distance,
        "locked_initial": locked,
        "locked_height_initial": locked_height,
        "old_release_period": old_release_period,
        "old_outbound_flow": old_outbound,
        "ship_outbound_flow": ship_outbound,
        "outbound_forecasts": outbound_forecasts,
        "ship_outbound_forecasts": ship_outbound_forecasts,
        "outbound_boxes_per_period": outbound_boxes_per_period,
        "cycles": cycles,
        "period_hours": PERIOD_HOURS,
        "execution_periods": EXECUTION_PERIODS,
        "receiving_periods": RECEIVING_PERIODS,
        "lookahead_periods": LOOKAHEAD_PERIODS,
        "seed": seed,
        "forecast_error": forecast_error,
        "forecast_error_mode": forecast_error_mode,
        "initial_utilization": initial_utilization,
        "containers_per_ship_range": containers_per_ship_range,
        "active_ship_overlap": active_ship_overlap,
        "pod_count": pod_count,
        "num_blocks": num_blocks,
        "bays_per_block": bays_per_block,
        "num_ships": num_ships,
    }


def build_repair_pressure_case(*, level: str = "nearby", seed: int = 0) -> dict:
    """Create a small deterministic case that exercises progressive repair."""
    if level not in ("nearby", "global"):
        raise ValueError("level must be nearby or global")
    case = build_synthetic_rolling_case(
        seed=seed,
        num_blocks=8,
        bays_per_block=4,
        num_ships=1,
        cycles=1,
        initial_utilization=0,
        forecast_error=0,
        containers_per_ship_range=(60, 60),
    )
    factor = 8 if level == "nearby" else 14
    case["forecasts"] = {
        key: value * factor for key, value in case["forecasts"].items()
    }
    case["pressure_level"] = level
    case["pressure_demand_factor"] = factor
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
    for block in case["blocks"]:
        for absolute in range(now, end):
            quantity = sum(
                value
                for (r, _old, k, period), value in case["outbound_forecasts"].items()
                if r == cycle and k == block and period == absolute
            )
            if quantity:
                outbound[block, absolute - now] = quantity
    for ship in case["ships"]:
        block_basis = {
            block: sum(
                quantity
                for (bay, j, _group), quantity in state["actual_inventory"].items()
                if j == ship and case["bay_block"][bay] == block
            )
            + sum(
                quantity
                for (bay, j, _group), quantity in previous_reservation.items()
                if j == ship and case["bay_block"][bay] == block
            )
            for block in case["blocks"]
        }
        if not sum(block_basis.values()):
            closest = min(case["blocks"], key=lambda block: case["distance"][ship, block])
            block_basis[closest] = 1
        for absolute in range(now, end):
            quantity = case["ship_outbound_forecasts"].get((cycle, ship, absolute), 0)
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
    return {key: case[key] for key in base_keys} | {
        "cycle": cycle,
        "absolute_start_period": now,
        "periods": list(range(case["lookahead_periods"])),
        "active_ships": active,
        "new_ships": new,
        "continuing_ships": continuing,
        "actual_inventory": dict(state["actual_inventory"]),
        "previous_reservation": previous_reservation,
        "previous_din": previous_din,
        "locked_inventory": dict(state["locked_inventory"]),
        "locked_height": dict(state["locked_height"]),
        "locked_release_local": locked_release,
        "ship_release_local": ship_release_local,
        "forecast_arrivals": forecast,
        "forecast_outbound": outbound,
        "remaining_demand": remaining,
        "release_period_basis": case["release_period_basis"],
    }


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
    end_space = _realized_space_metrics(case, next_state, boundary)
    metrics.update({key: value for key, value in end_space.items() if key != "support"})
    metrics["realized_new_support_count"] = len(end_space["support"] - start_support)
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

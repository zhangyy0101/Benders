"""Dependency-aware impact regions, progressive repair, and validation."""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Mapping
from typing import TypeAlias

import gurobipy as gp
from gurobipy import GRB

from config import (
    ADAPTIVE_BLOCK_BATCH_RATIO,
    ADAPTIVE_GLOBAL_BYPASS_ENABLED,
    ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD,
    ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD,
    AGGREGATE_DOMAIN_LADDER_BUDGET_RATIO,
    AGGREGATE_DOMAIN_LADDER_BUFFER_MULTIPLIER,
    AGGREGATE_DOMAIN_LADDER_ENABLED,
    AGGREGATE_DOMAIN_LADDER_LEVELS,
    AGGREGATE_DOMAIN_LADDER_MAX_SECONDS,
    BOTTLENECK_SELECTOR_BUDGET_RATIO,
    BOTTLENECK_SELECTOR_MAX_SECONDS,
    DEPENDENCY_CANDIDATE_BLOCK_RATIO,
    DEPENDENCY_DECAY,
    DEPENDENCY_EDGE_THRESHOLD,
    DEPENDENCY_MAX_DEPTH,
    DEPENDENCY_MAX_NEIGHBORS_PER_PAIR,
    DEPENDENCY_PATH_THRESHOLD,
    DEPENDENCY_PROFILES,
    DEPENDENCY_PROPAGATION_ENABLED,
    DEPENDENCY_TRIGGER_MODE,
    DEPENDENCY_WEIGHT_CANDIDATE_OVERLAP,
    DEPENDENCY_WEIGHT_CAPACITY_PRESSURE,
    DEPENDENCY_WEIGHT_HISTORICAL_OVERLAP,
    DEPENDENCY_WEIGHT_TEMPORAL_OVERLAP,
    IMPACT_SCORE_BALANCE_WEIGHT,
    IMPACT_SCORE_BAY_WEIGHT,
    IMPACT_SCORE_CAPACITY_WEIGHT,
    IMPACT_SCORE_DISTANCE_WEIGHT,
    IMPACT_SCORE_OUTBOUND_WEIGHT,
    IMPACT_SCORE_STABILITY_WEIGHT,
    GLOBAL_CORE_HEURISTICS,
    GLOBAL_CORE_MIP_FOCUS,
    GLOBAL_CORE_START_NODE_LIMIT,
    GLOBAL_REPAIR_MIN_START_SECONDS,
    GLOBAL_REPAIR_RESERVE_MAX_SECONDS,
    GLOBAL_REPAIR_RESERVE_MIN_SECONDS,
    GLOBAL_REPAIR_RESERVE_RATIO,
    QUALITY_POLISH_BLOCKS_PER_PAIR,
    QUALITY_POLISH_ENABLED,
    QUALITY_POLISH_PAIR_RATIO,
    QUALITY_POLISH_WEIGHT_DISTANCE,
    QUALITY_POLISH_WEIGHT_OVERLAP,
    QUALITY_POLISH_WEIGHT_SUPPORT,
    QUALITY_POLISH_WEIGHT_UTILIZATION,
    SOLVER_RETURN_GUARD_MAX_SECONDS,
    SOLVER_RETURN_GUARD_MIN_SECONDS,
    SOLVER_RETURN_GUARD_RATIO,
    POSTPROCESSING_RESERVE_MAX_SECONDS,
    POSTPROCESSING_RESERVE_MIN_SECONDS,
    POSTPROCESSING_RESERVE_RATIO,
    STABILITY_BLOCK_REALLOCATION_WEIGHT,
    STABILITY_CANCEL_WEIGHT,
    STABILITY_NEW_BAY_WEIGHT,
    TIME_CAPACITY_WEIGHT,
    USE_EXACT_STABILITY_BIG_M,
    MINIMUM_PERIOD_CAPACITY_WEIGHT,
    WALL_TIME_TOLERANCE_SECONDS,
)
from rolling_model import (
    build_rolling_model,
    compatible,
    compute_objective_scales,
    evaluate_operation_components,
    existing_blocks,
    existing_support,
    extract_rolling_solution,
    reservation_support,
    ship_present_at,
)

Pair: TypeAlias = tuple[str, str]
INF = 10**9
CONFIGURATIONS = (
    "core",
    "core_start",
    "core_start_impact",
    "full_direct",
    "full_bottleneck",
    "full_bottleneck_no_aggregate",
    "full",
)


def postprocessing_reserve_seconds(time_limit: float) -> float:
    """Reserve a common bounded online tail for incumbent extraction."""
    limit = max(0.0, float(time_limit))
    if limit <= 0:
        return 0.0
    target = min(
        POSTPROCESSING_RESERVE_MAX_SECONDS,
        max(
            POSTPROCESSING_RESERVE_MIN_SECONDS,
            POSTPROCESSING_RESERVE_RATIO * limit,
        ),
    )
    return min(.50 * limit, target)


def solver_return_guard_seconds(time_limit: float, solver_window: float) -> float:
    """Return the common in-budget guard for solver termination cleanup."""

    window = max(0.0, float(solver_window))
    if window <= .01:
        return 0.0
    target = min(
        SOLVER_RETURN_GUARD_MAX_SECONDS,
        max(
            SOLVER_RETURN_GUARD_MIN_SECONDS,
            SOLVER_RETURN_GUARD_RATIO * max(0.0, float(time_limit)),
        ),
    )
    return min(max(0.0, window - .01), target)


def global_repair_reserve_seconds(
    time_limit: float,
    remaining_window: float,
) -> float:
    """Reserve a bounded in-budget window after bottleneck repair.

    The reserve is used only when a shortage-bearing incumbent has already
    triggered the bottleneck stage.  It is capped at half of the remaining
    optimization window so the restricted exact repair always keeps the larger
    share when little time remains.
    """

    limit = max(0.0, float(time_limit))
    window = max(0.0, float(remaining_window))
    if limit <= 0 or window <= 0:
        return 0.0
    target = min(
        GLOBAL_REPAIR_RESERVE_MAX_SECONDS,
        max(
            GLOBAL_REPAIR_RESERVE_MIN_SECONDS,
            GLOBAL_REPAIR_RESERVE_RATIO * limit,
        ),
    )
    return min(.50 * window, target)


def _post_bottleneck_global_repair_decision(
    *,
    stage_name: str,
    predicted_shortage: float | None,
    remaining_wall: float,
    already_scheduled: bool,
) -> tuple[bool, str]:
    """Decide whether residual bottleneck shortage reaches global recovery."""

    if stage_name != "bottleneck_repair":
        return False, "not_applicable"
    if predicted_shortage is None:
        return False, "skipped_without_incumbent"
    if predicted_shortage <= 1e-6:
        return False, "not_needed_zero_shortage"
    if already_scheduled:
        return False, "already_scheduled"
    if remaining_wall <= GLOBAL_REPAIR_MIN_START_SECONDS:
        return False, "skipped_insufficient_time"
    return True, "enqueued_residual_shortage"


def _restricted_build_timeout_transition(
    *,
    progressive_repair: bool,
    stage_level: int,
    stage_name: str,
    incumbent_shortage: float | None,
    remaining_wall: float,
    global_already_scheduled: bool,
) -> tuple[str, str]:
    """Choose a safe continuation when a restricted model cannot start.

    A stage-local build allowance must not terminate a progressive controller
    while the common online window can still run the unrestricted safety MIP.
    Existing feasible incumbents are retained regardless of this transition.
    """
    if not progressive_repair:
        return "finish", "configured_without_progressive_repair"
    if stage_level == 3:
        return "finish", "global_model_build_timeout"
    if stage_name == "quality_polish":
        return "finish", "preserve_incumbent_after_quality_build_timeout"
    if incumbent_shortage is not None and incumbent_shortage <= 1e-6:
        return "finish", "preserve_zero_shortage_incumbent"
    if remaining_wall <= GLOBAL_REPAIR_MIN_START_SECONDS:
        return "finish", "skipped_insufficient_time"
    if global_already_scheduled:
        return "continue", "continue_scheduled_global_after_build_timeout"
    return "enqueue", "enqueued_global_after_restricted_build_timeout"


def configuration_features(configuration: str) -> dict:
    """Expose ablation switches so tests and experiment metadata stay aligned."""
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"configuration must be one of {CONFIGURATIONS}")
    return {
        "mip_start": configuration != "core",
        "impact_region": configuration not in ("core", "core_start"),
        "dependency_propagation": configuration == "full" and DEPENDENCY_PROPAGATION_ENABLED,
        "progressive_repair": configuration in (
            "full_direct",
            "full_bottleneck",
            "full_bottleneck_no_aggregate",
            "full",
        ),
        "bottleneck_repair": configuration in (
            "full_bottleneck",
            "full_bottleneck_no_aggregate",
        ),
        "adaptive_global_bypass": (
            configuration in (
                "full_bottleneck",
                "full_bottleneck_no_aggregate",
            )
            and ADAPTIVE_GLOBAL_BYPASS_ENABLED
        ),
        "aggregate_domain_ladder": (
            configuration == "full_bottleneck"
            and AGGREGATE_DOMAIN_LADDER_ENABLED
        ),
        "quality_polish": (
            QUALITY_POLISH_ENABLED
            and configuration in (
                "full_direct",
                "full_bottleneck",
                "full_bottleneck_no_aggregate",
                "full",
            )
        ),
    }


def _snapshot_pressure_diagnostics(
    d: dict,
    direct_pairs: set[Pair],
) -> dict:
    """Diagnose severe snapshot pressure without using instance-size labels.

    The peak-load term respects the forecast arrival path and vessel presence.
    The demand/free-capacity term detects snapshots where restricted repair is
    likely to consume most of the domain before falling back to the Global MIP.
    Requiring both tests keeps ordinary rolling cycles on the fast local path.
    """
    total_capacity = float(sum(d["capacity"].values()))
    remaining_demand = float(sum(d["remaining_demand"].values()))
    period_load: dict[int, float] = {}
    for period in d["periods"]:
        locked = sum(
            quantity
            for (bay, old_ship), quantity in d["locked_inventory"].items()
            if d["locked_release_local"].get((bay, old_ship), INF) > period
        )
        actual = sum(
            quantity
            for (_bay, ship, _group), quantity in d["actual_inventory"].items()
            if ship_present_at(d, ship, period)
        )
        forecast = sum(
            quantity
            for (ship, _group, arrival), quantity in d["forecast_arrivals"].items()
            if arrival <= period and ship_present_at(d, ship, period)
        )
        period_load[period] = float(locked + actual + forecast)

    peak_period, peak_load = max(
        period_load.items(),
        key=lambda item: (item[1], -item[0]),
        default=(None, 0.0),
    )
    first_period = d["periods"][0]
    initial_occupied = period_load.get(first_period, 0.0) - sum(
        quantity
        for (ship, _group, arrival), quantity in d["forecast_arrivals"].items()
        if arrival <= first_period and ship_present_at(d, ship, first_period)
    )
    initial_free_capacity = max(0.0, total_capacity - initial_occupied)
    peak_load_ratio = peak_load / max(1.0, total_capacity)
    demand_free_ratio = remaining_demand / max(1.0, initial_free_capacity)
    active_pair_count = len(d["remaining_demand"])
    direct_pair_ratio = len(direct_pairs) / max(1, active_pair_count)
    pressure_index = min(
        peak_load_ratio / max(1e-9, ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD),
        demand_free_ratio
        / max(1e-9, ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD),
    )
    route_to_global = (
        peak_load_ratio + 1e-12 >= ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD
        and demand_free_ratio + 1e-12
        >= ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD
    )
    return {
        "policy": "joint_peak_load_and_demand_free_capacity",
        "route": "global_core" if route_to_global else "bottleneck_repair",
        "route_to_global": route_to_global,
        "peak_period": peak_period,
        "peak_forecast_load": peak_load,
        "peak_load_ratio": peak_load_ratio,
        "remaining_demand": remaining_demand,
        "initial_free_capacity": initial_free_capacity,
        "demand_free_capacity_ratio": demand_free_ratio,
        "direct_pair_count": len(direct_pairs),
        "active_pair_count": active_pair_count,
        "direct_pair_ratio": direct_pair_ratio,
        "pressure_index": pressure_index,
        "peak_load_threshold": ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD,
        "demand_free_capacity_threshold": (
            ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD
        ),
    }


def _restricted_domain_aggregate_capacity_margin(
    d: dict,
    allowed_bays: dict[Pair, list[str]],
    *,
    uncertainty_radius: float,
    time_limit: float,
    threads: int = 1,
) -> dict:
    """Measure a restricted domain's aggregate forecast-capacity margin.

    The LP maximizes a common demand multiplier while aggregating flow to
    block-size-height resources. Existing bay heights split residual capacity
    into fixed-height and flexible pools. This is a relaxation of bay-level
    integer packing: passing the screen selects a candidate domain, while the
    downstream integer MIP and independent validation remain the exact guards.
    ``uncertainty_radius`` is therefore a deterministic screening buffer, not a
    claimed probabilistic confidence radius.
    """
    if uncertainty_radius < 0:
        raise ValueError("uncertainty_radius must be nonnegative")
    required_scale = 1.0 + float(uncertainty_radius)
    if time_limit <= 0:
        return {
            "classification": "unknown",
            "route_to_global": None,
            "required_scale": required_scale,
            "maximum_scale": None,
            "maximum_scale_bound": None,
            "reason": "no_time_budget",
        }
    attrs = d["group_attrs"]
    periods = tuple(d["periods"])
    demand = {
        key: float(quantity)
        for key, quantity in d["forecast_arrivals"].items()
        if quantity > 0 and ship_present_at(d, key[0], key[2])
    }
    if not demand:
        return {
            "classification": "aggregate_margin_pass",
            "route_to_global": False,
            "required_scale": required_scale,
            "maximum_scale": None,
            "maximum_scale_bound": None,
            "reason": "no_positive_forecast_demand",
        }

    allowed_blocks = {
        pair: {
            d["bay_block"][bay]
            for bay in allowed_bays.get(pair, ())
            if compatible(d, bay, pair[1])
        }
        for pair in d["remaining_demand"]
    }
    flow_keys = [
        (block, ship, group, arrival)
        for ship, group, arrival in sorted(demand)
        for block in sorted(allowed_blocks.get((ship, group), ()))
    ]

    model = gp.Model("restricted_domain_aggregate_capacity_margin")
    model.Params.OutputFlag = 0
    model.Params.Threads = max(1, int(threads))
    model.Params.TimeLimit = max(.001, float(time_limit))
    model.Params.Method = 1
    scale = model.addVar(
        lb=0,
        ub=100,
        vtype=GRB.CONTINUOUS,
        name="uniform_demand_scale",
    )
    flow = model.addVars(
        flow_keys,
        lb=0,
        vtype=GRB.CONTINUOUS,
        name="flow",
    )
    sizes = tuple(sorted(set(d["bay_size"].values())))
    flexible_capacity = model.addVars(
        [
            (block, size, height, period)
            for block in d["blocks"]
            for size in sizes
            for height in d["heights"]
            for period in periods
        ],
        lb=0,
        vtype=GRB.CONTINUOUS,
        name="flex_capacity",
    )

    for demand_key, quantity in demand.items():
        ship, group, arrival = demand_key
        model.addConstr(
            gp.quicksum(
                flow[block, ship, group, arrival]
                for block in allowed_blocks.get((ship, group), ())
            )
            == quantity * scale
        )

    flow_by_resource: dict[
        tuple[str, int, str, int],
        list[tuple[str, str, str, int]],
    ] = defaultdict(list)
    for key in flow_keys:
        block, ship, group, arrival = key
        size = attrs[group]["size"]
        height = attrs[group]["height"]
        for period in periods:
            if arrival <= period and ship_present_at(d, ship, period):
                flow_by_resource[block, size, height, period].append(key)

    locked_by_bay: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for (bay, old_ship), quantity in d["locked_inventory"].items():
        locked_by_bay[bay].append(
            (old_ship, quantity, d["locked_height"][bay, old_ship])
        )
    actual_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (bay, ship, group), quantity in d["actual_inventory"].items():
        actual_by_bay[bay].append((ship, group, quantity))

    for block in d["blocks"]:
        for size in sizes:
            resource_bays = [
                bay
                for bay in d["bays_in_block"][block]
                if d["bay_size"][bay] == size
            ]
            for period in periods:
                fixed_remaining = {
                    height: 0.0 for height in d["heights"]
                }
                flexible_total = 0.0
                for bay in resource_bays:
                    occupied = 0.0
                    occupied_heights: set[str] = set()
                    for old_ship, quantity, height in locked_by_bay[bay]:
                        if d["locked_release_local"].get((bay, old_ship), INF) > period:
                            occupied += quantity
                            occupied_heights.add(height)
                    for ship, group, quantity in actual_by_bay[bay]:
                        if ship_present_at(d, ship, period):
                            occupied += quantity
                            occupied_heights.add(attrs[group]["height"])
                    if len(occupied_heights) > 1:
                        model.dispose()
                        return {
                            "classification": "unknown",
                            "route_to_global": None,
                            "required_scale": required_scale,
                            "maximum_scale": None,
                            "maximum_scale_bound": None,
                            "reason": "inconsistent_existing_height_state",
                        }
                    residual = max(0.0, d["capacity"][bay] - occupied)
                    if occupied_heights:
                        fixed_remaining[next(iter(occupied_heights))] += residual
                    else:
                        flexible_total += residual
                model.addConstr(
                    gp.quicksum(
                        flexible_capacity[block, size, height, period]
                        for height in d["heights"]
                    )
                    <= flexible_total
                )
                for height in d["heights"]:
                    model.addConstr(
                        gp.quicksum(
                            flow[key]
                            for key in flow_by_resource[
                                block, size, height, period
                            ]
                        )
                        <= fixed_remaining[height]
                        + flexible_capacity[block, size, height, period]
                    )

    model.setObjective(scale, GRB.MAXIMIZE)
    model.optimize()
    status = int(model.Status)
    solution_count = int(model.SolCount)
    incumbent_scale = float(model.ObjVal) if solution_count else None
    try:
        scale_bound = float(model.ObjBound)
        if not math.isfinite(scale_bound):
            scale_bound = None
    except (AttributeError, ValueError):
        scale_bound = None

    tolerance = 1e-7
    if incumbent_scale is not None and incumbent_scale + tolerance >= required_scale:
        classification = "aggregate_margin_pass"
        route_to_global = False
    elif scale_bound is not None and scale_bound < required_scale - tolerance:
        classification = (
            "aggregate_nominal_deficit"
            if scale_bound < 1.0 - tolerance
            else "aggregate_buffer_shortfall"
        )
        route_to_global = True
    else:
        classification = "unknown"
        route_to_global = None
    result = {
        "classification": classification,
        "route_to_global": route_to_global,
        "required_scale": required_scale,
        "maximum_scale": incumbent_scale,
        "maximum_scale_bound": scale_bound,
        "uncertainty_buffer": float(uncertainty_radius),
        "solver_status": status,
        "solution_count": solution_count,
        "runtime_seconds": float(model.Runtime),
        "flow_variable_count": len(flow_keys),
        "model_variable_count": int(model.NumVars),
        "model_constraint_count": int(model.NumConstrs),
        "reason": "uniform_block_size_height_capacity_relaxation",
        "screen_is_relaxation": True,
        "exact_feasibility_guard": "downstream_integer_mip_and_validation",
    }
    model.dispose()
    return result


def _select_aggregate_domain_ladder(
    d: dict,
    direct_pairs: set[Pair],
    propagated_pairs: set[Pair],
    scores: dict,
    *,
    uncertainty_radius: float,
    time_limit: float,
    threads: int = 1,
    release_opportunity_blocks: dict[Pair, set[str]] | None = None,
) -> tuple[int, dict]:
    """Choose the smallest domain that passes the buffered aggregate-LP screen."""
    started = time.perf_counter()
    deadline = started + max(0.0, time_limit)
    evaluations: list[dict] = []
    seen_domains: dict[tuple, dict] = {}
    selected_level = 3
    selection_reason = "global_safety_fallback"

    for level in AGGREGATE_DOMAIN_LADDER_LEVELS:
        allowed = _allowed(
            d,
            level,
            direct_pairs,
            propagated_pairs,
            scores,
            repair_pairs=direct_pairs if level > 0 else set(),
            release_opportunity_blocks=release_opportunity_blocks,
        )
        signature = tuple(
            (pair, tuple(allowed[pair])) for pair in sorted(allowed)
        )
        if signature in seen_domains:
            margin = dict(seen_domains[signature])
            duplicate_of = next(
                record["level"]
                for record in evaluations
                if record.get("domain_signature") == signature
            )
        else:
            remaining = deadline - time.perf_counter()
            if remaining <= .005:
                margin = {
                    "classification": "unknown",
                    "route_to_global": None,
                    "required_scale": 1.0 + uncertainty_radius,
                    "maximum_scale": None,
                    "maximum_scale_bound": None,
                    "reason": "ladder_time_budget_exhausted",
                }
            else:
                margin = _restricted_domain_aggregate_capacity_margin(
                    d,
                    allowed,
                    uncertainty_radius=uncertainty_radius,
                    time_limit=remaining,
                    threads=threads,
                )
            seen_domains[signature] = dict(margin)
            duplicate_of = None
        record = {
            "level": level,
            "domain": f"N{level}",
            "allowed_pair_bay_count": sum(
                len(bays) for bays in allowed.values()
            ),
            "duplicate_of_level": duplicate_of,
            "domain_signature": signature,
            **margin,
        }
        evaluations.append(record)
        if margin["classification"] == "aggregate_margin_pass":
            selected_level = level
            selection_reason = "smallest_aggregate_lp_screened_domain"
            break

    if selected_level == 3:
        global_allowed = {
            pair: [
                bay
                for bay in d["bays"]
                if compatible(d, bay, pair[1])
            ]
            for pair in sorted(d["remaining_demand"])
        }
        signature = tuple(
            (pair, tuple(global_allowed[pair]))
            for pair in sorted(global_allowed)
        )
        if signature in seen_domains:
            global_margin = dict(seen_domains[signature])
            duplicate_of = next(
                record["level"]
                for record in evaluations
                if record.get("domain_signature") == signature
            )
        else:
            remaining = deadline - time.perf_counter()
            if remaining <= .005:
                global_margin = {
                    "classification": "unknown",
                    "route_to_global": None,
                    "required_scale": 1.0 + uncertainty_radius,
                    "maximum_scale": None,
                    "maximum_scale_bound": None,
                    "reason": "ladder_time_budget_exhausted",
                }
            else:
                global_margin = _restricted_domain_aggregate_capacity_margin(
                    d,
                    global_allowed,
                    uncertainty_radius=uncertainty_radius,
                    time_limit=remaining,
                    threads=threads,
                )
            seen_domains[signature] = dict(global_margin)
            duplicate_of = None
        evaluations.append({
            "level": 3,
            "domain": "Global",
            "allowed_pair_bay_count": sum(
                len(bays) for bays in global_allowed.values()
            ),
            "duplicate_of_level": duplicate_of,
            "domain_signature": signature,
            **global_margin,
        })
        selected_level = 3
        selection_reason = (
            "global_is_first_aggregate_lp_screened_domain"
            if global_margin["classification"] == "aggregate_margin_pass"
            else "global_safety_fallback_without_buffered_domain"
        )

    finite_scales = [
        record["maximum_scale"]
        for record in evaluations
        if record.get("maximum_scale") is not None
        and record.get("duplicate_of_level") is None
    ]
    diagnostics = {
        "policy": "buffered_aggregate_lp_domain_ladder",
        "uncertainty_buffer": float(uncertainty_radius),
        "required_scale": 1.0 + float(uncertainty_radius),
        "selected_level": selected_level,
        "selected_domain": (
            "Global" if selected_level == 3 else f"N{selected_level}"
        ),
        "selection_reason": selection_reason,
        "screen_is_relaxation": True,
        "exact_feasibility_guard": "downstream_integer_mip_and_validation",
        "evaluations": [
            {
                key: value
                for key, value in record.items()
                if key != "domain_signature"
            }
            for record in evaluations
        ],
        "evaluated_unique_domain_count": len(seen_domains),
        "margin_monotonic": all(
            right + 1e-7 >= left
            for left, right in zip(finite_scales, finite_scales[1:])
        ),
        "runtime_seconds": time.perf_counter() - started,
    }
    return selected_level, diagnostics


def _incumbent_key(components: dict) -> tuple[float, float, float]:
    """Return the common protected lexicographic quality key."""
    return (
        round(components["predicted_shortage"], 6),
        round(components["stability_cost"], 6),
        round(components["normalized_operations_score"], 9),
    )


def _incumbent_decision(
    candidate_key: tuple[float, float, float],
    best_key: tuple[float, float, float] | None,
) -> tuple[bool, str]:
    """Accept only a strict lexicographic improvement over the incumbent."""
    if best_key is None:
        return True, "first_feasible_incumbent"
    if candidate_key < best_key:
        improved_index = next(
            index
            for index, (candidate, incumbent) in enumerate(
                zip(candidate_key, best_key)
            )
            if candidate != incumbent
        )
        return True, (
            "improved_predicted_shortage"
            if improved_index == 0
            else "improved_stability"
            if improved_index == 1
            else "improved_normalized_operations"
        )
    return False, "not_lexicographically_better"


def _pair_totals(reservation: dict) -> dict[Pair, float]:
    totals: dict[Pair, float] = {}
    for (_i, j, g), q in reservation.items():
        totals[j, g] = totals.get((j, g), 0) + q
    return totals


def _direct_impact_pairs(d: dict, threshold: float) -> tuple[set[Pair], dict[Pair, list[str]]]:
    """Identify changed ship-group pairs without promoting their whole ship."""
    old = _pair_totals(d["previous_reservation"])
    current = d["remaining_demand"]
    direct: set[Pair] = set()
    reasons: dict[Pair, list[str]] = {}
    for pair in sorted(set(old) | set(current)):
        j, _g = pair
        previous, demand = old.get(pair, 0), current.get(pair, 0)
        pair_reasons = []
        if j in d["new_ships"] and demand > 0:
            pair_reasons.append("new_ship")
        if previous == 0 and demand > 0:
            pair_reasons.append("new_positive_demand")
        if previous > 0 and demand == 0:
            pair_reasons.append("demand_disappeared")
        if previous > 0 and abs(demand - previous) / max(1, previous) >= threshold:
            pair_reasons.append("relative_demand_change")
        if pair_reasons:
            direct.add(pair)
            reasons[pair] = pair_reasons
    return direct, reasons


def _impact_directions(d: dict) -> dict[Pair, str]:
    """Classify visible demand changes without using hidden realization data."""
    old = _pair_totals(d["previous_reservation"])
    current = d["remaining_demand"]
    directions: dict[Pair, str] = {}
    for pair in sorted(set(old) | set(current)):
        previous, demand = old.get(pair, 0), current.get(pair, 0)
        if previous <= 0 < demand:
            directions[pair] = "new"
        elif previous > 0 and demand <= 0:
            directions[pair] = "disappear"
        elif demand > previous:
            directions[pair] = "increase"
        elif demand < previous:
            directions[pair] = "decrease"
        else:
            directions[pair] = "unchanged"
    return directions


def _stability_reference_diagnostics(d: dict) -> dict:
    """Describe the rolling-plan reference without imposing a hard budget."""
    old = _pair_totals(d["previous_reservation"])
    current = d["remaining_demand"]
    keys = set(old) | set(current)
    prediction_change = sum(abs(current.get(key, 0) - old.get(key, 0)) for key in keys)
    mandatory = sum(max(0, old.get(key, 0) - current.get(key, 0)) for key in keys)
    return {
        "policy": "second_lexicographic_objective_without_hard_budget",
        "hard_stability_budget_enabled": False,
        "mandatory_reduction": mandatory,
        "prediction_change": prediction_change,
        "previous_reservation": sum(old.values()),
        "pair_prediction_change_basis": {
            pair: abs(current.get(pair, 0) - old.get(pair, 0))
            for pair in sorted(keys)
            if abs(current.get(pair, 0) - old.get(pair, 0)) > 0
        },
    }


def _dependency_pairs(d: dict) -> set[Pair]:
    return set(d["remaining_demand"]) | {
        (ship, group)
        for (_bay, ship, group), quantity in d["previous_reservation"].items()
        if quantity > 0
    }


def physical_residual_capacity_by_bay_period(
    d: dict,
) -> dict[tuple[str, int], float]:
    """Return physical capacity after locked and currently realized inventory."""
    locked_by_bay: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for (bay, old_ship), quantity in d["locked_inventory"].items():
        locked_by_bay[bay].append((
            d["locked_release_local"].get((bay, old_ship), INF),
            quantity,
        ))
    actual_by_bay: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (bay, ship, _group), quantity in d["actual_inventory"].items():
        actual_by_bay[bay].append((ship, quantity))
    presence = {
        (ship, period): ship_present_at(d, ship, period)
        for entries in actual_by_bay.values()
        for ship, _quantity in entries
        for period in d["periods"]
    }
    residual: dict[tuple[str, int], float] = {}
    for bay in d["bays"]:
        for period in d["periods"]:
            locked = sum(
                quantity
                for release, quantity in locked_by_bay[bay]
                if release > period
            )
            actual = sum(
                quantity
                for ship, quantity in actual_by_bay[bay]
                if presence[ship, period]
            )
            residual[bay, period] = max(0.0, d["capacity"][bay] - locked - actual)
    return residual


def residual_capacity_by_bay_period(d: dict) -> dict[tuple[str, int], float]:
    """Backward-compatible alias for physical residual capacity."""
    return physical_residual_capacity_by_bay_period(d)


def baseline_residual_capacity_by_bay_period(
    d: dict,
    frozen_pairs: set[Pair],
    physical: dict[tuple[str, int], float] | None = None,
) -> dict[tuple[str, int], float]:
    """Deduct time-dependent commitments of inherited, unaffected plans."""
    physical = physical or physical_residual_capacity_by_bay_period(d)
    previous_din = d.get("previous_din", {})
    schedules: dict[
        tuple[str, str, str], list[tuple[int, float]]
    ] = defaultdict(list)
    for (bay, ship, group, arrival), quantity in previous_din.items():
        schedules[bay, ship, group].append((arrival, quantity))
    commitment_keys = {
        key
        for key in schedules
        if (key[1], key[2]) in frozen_pairs
    } | {
        (bay, ship, group)
        for (bay, ship, group), _quantity
        in d["previous_reservation"].items()
        if (
            (ship, group) in frozen_pairs
            and (bay, ship, group) not in schedules
        )
    }
    commitments_by_bay: dict[
        str, list[tuple[str, str, dict[int, float]]]
    ] = defaultdict(list)
    for bay, ship, group in sorted(commitment_keys):
        if (bay, ship, group) in schedules:
            by_period = {
                period: sum(
                    quantity
                    for arrival, quantity in schedules[bay, ship, group]
                    if arrival <= period
                )
                for period in d["periods"]
            }
        else:
            value = d["previous_reservation"].get(
                (bay, ship, group), 0
            )
            by_period = {period: value for period in d["periods"]}
        commitments_by_bay[bay].append((ship, group, by_period))
    presence = {
        (ship, period): ship_present_at(d, ship, period)
        for entries in commitments_by_bay.values()
        for ship, _group, _by_period in entries
        for period in d["periods"]
    }
    result: dict[tuple[str, int], float] = {}
    for bay in d["bays"]:
        for period in d["periods"]:
            committed = 0.0 + sum(
                by_period[period]
                for ship, _group, by_period in commitments_by_bay[bay]
                if presence[ship, period]
            )
            result[bay, period] = max(0.0, physical[bay, period] - committed)
    return result


def _base_heights(d: dict, bay: str, period: int) -> set[str]:
    attrs = d["group_attrs"]
    return {
        height
        for (i, old_ship), height in d["locked_height"].items()
        if i == bay and d["locked_release_local"].get((i, old_ship), INF) > period
    } | {
        attrs[group]["height"]
        for (i, ship, group), quantity in d["actual_inventory"].items()
        if i == bay and quantity > 0 and ship_present_at(d, ship, period)
    }


def _base_heights_by_bay_period(
    d: dict,
) -> dict[tuple[str, int], set[str]]:
    """Index immutable height occupancy once for all pair-block scores."""
    locked_by_bay: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for (bay, old_ship), height in d["locked_height"].items():
        locked_by_bay[bay].append((
            d["locked_release_local"].get((bay, old_ship), INF),
            height,
        ))
    actual_by_bay: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (bay, ship, group), quantity in d["actual_inventory"].items():
        if quantity > 0:
            actual_by_bay[bay].append((
                ship,
                d["group_attrs"][group]["height"],
            ))
    presence = {
        (ship, period): ship_present_at(d, ship, period)
        for entries in actual_by_bay.values()
        for ship, _height in entries
        for period in d["periods"]
    }
    return {
        (bay, period): {
            height
            for release, height in locked_by_bay[bay]
            if release > period
        } | {
            height
            for ship, height in actual_by_bay[bay]
            if presence[ship, period]
        }
        for bay in d["bays"]
        for period in d["periods"]
    }


def _pair_time_profile(d: dict, pair: Pair) -> tuple[dict[int, float], dict[int, float]]:
    """Return visible quantity profile and normalized temporal weights."""
    ship, group = pair
    profile = {
        period: float(d["forecast_arrivals"].get((ship, group, period), 0))
        for period in d["periods"]
    }
    total = sum(profile.values())
    if total <= 0:
        profile = {
            period: float(sum(
                quantity
                for (_bay, j, g, n), quantity in d.get("previous_din", {}).items()
                if j == ship and g == group and n == period
            ))
            for period in d["periods"]
        }
        total = sum(profile.values())
    if total <= 0:
        eligible_periods = [
            period for period in d["periods"]
            if period >= d.get("execution_periods", 0)
        ] or list(d["periods"])
        profile = {period: float(period in eligible_periods) for period in d["periods"]}
        total = float(len(eligible_periods))
    weights = {period: profile[period] / max(1.0, total) for period in d["periods"]}
    return profile, weights


def _block_scores(
    d: dict,
    residual: dict[tuple[str, int], float] | None = None,
    *,
    capacity_basis: str = "physical",
) -> dict:
    """Rank blocks using arrival-weighted residual capacity and height feasibility."""
    scores: dict = {}
    periods, attrs = d["periods"], d["group_attrs"]
    residual = residual or physical_residual_capacity_by_bay_period(d)
    max_dist = max(d["distance"].values(), default=1)
    max_out = max(d["forecast_outbound"].values(), default=1)
    block_capacity = {
        block: sum(d["capacity"][bay] for bay in d["bays_in_block"][block])
        for block in d["blocks"]
    }
    base_utilization = {
        (block, period): 1.0 - sum(
            residual[bay, period] for bay in d["bays_in_block"][block]
        ) / max(1, block_capacity[block])
        for block in d["blocks"]
        for period in periods
    }
    old_totals = _pair_totals(d["previous_reservation"])
    base_heights = _base_heights_by_bay_period(d)
    compatible_bays_by_group_block = {
        (group, block): tuple(
            bay
            for bay in d["bays_in_block"][block]
            if compatible(d, bay, group)
        )
        for group in attrs
        for block in d["blocks"]
    }
    for ship, group in sorted(_dependency_pairs(d)):
        pair = (ship, group)
        height = attrs[group]["height"]
        current_demand = d["remaining_demand"].get(pair, 0)
        released_quantity = max(0, old_totals.get(pair, 0) - current_demand)
        demand_basis = max(1, current_demand or released_quantity)
        profile, weights = _pair_time_profile(d, pair)
        support_blocks = existing_blocks(d, ship, group)
        for block in d["blocks"]:
            capacity_by_period: dict[int, float] = {}
            conflict_by_period: dict[int, int] = {}
            compatible_bays = compatible_bays_by_group_block[group, block]
            for period in periods:
                capacity = 0.0
                conflicts = 0
                for bay in compatible_bays:
                    fixed_heights = base_heights[bay, period]
                    if fixed_heights and height not in fixed_heights:
                        conflicts += 1
                    else:
                        capacity += residual[bay, period]
                capacity_by_period[period] = capacity
                conflict_by_period[period] = conflicts
            effective_capacity = sum(
                weights[period] * capacity_by_period[period] for period in periods
            )
            arrival_periods = [period for period in periods if profile[period] > 0]
            minimum_capacity = min(
                (capacity_by_period[period] for period in arrival_periods),
                default=0.0,
            )
            weighted_ratio = min(1.0, effective_capacity / demand_basis)
            minimum_ratio = min(1.0, minimum_capacity / demand_basis)
            capacity_ratio = (
                TIME_CAPACITY_WEIGHT * weighted_ratio
                + MINIMUM_PERIOD_CAPACITY_WEIGHT * minimum_ratio
            )
            weighted_height_conflict = sum(
                weights[period]
                * conflict_by_period[period]
                / max(1, len(compatible_bays))
                for period in periods
            )
            distance = d["distance"].get((ship, block), max_dist) / max_dist
            overlap = sum(
                profile[period] * d["forecast_outbound"].get((block, period), 0)
                for period in periods
            ) / (max(1, sum(profile.values())) * max_out)
            balance_delta = 0.0
            for period in periods:
                values = [base_utilization[k, period] for k in d["blocks"]]
                before_mean = sum(values) / max(1, len(values))
                before = sum(abs(value - before_mean) for value in values)
                position = d["blocks"].index(block)
                values[position] += sum(
                    profile[t] for t in periods if t <= period
                ) / max(1, block_capacity[block])
                after_mean = sum(values) / max(1, len(values))
                balance_delta += sum(abs(value - after_mean) for value in values) - before
            balance_delta /= max(1, len(periods))
            estimated_bays = math.ceil(demand_basis / max(1, max(
                (residual[bay, period] for bay in compatible_bays for period in periods),
                default=1,
            )))
            bay_penalty = min(1.0, estimated_bays / 3)
            stability_loss = int(bool(support_blocks) and block not in support_blocks)
            score = (
                IMPACT_SCORE_CAPACITY_WEIGHT * capacity_ratio
                - IMPACT_SCORE_DISTANCE_WEIGHT * distance
                - IMPACT_SCORE_OUTBOUND_WEIGHT * overlap
                - IMPACT_SCORE_BALANCE_WEIGHT * balance_delta
                - IMPACT_SCORE_BAY_WEIGHT * bay_penalty
                - IMPACT_SCORE_STABILITY_WEIGHT * stability_loss
                - weighted_height_conflict
            )
            scores[ship, group, block] = {
                "score": score,
                "compatible_capacity": effective_capacity,
                "effective_capacity": effective_capacity,
                "minimum_arrival_period_capacity": minimum_capacity,
                "capacity_by_period": capacity_by_period,
                "arrival_weight": weights,
                "capacity_ratio": capacity_ratio,
                "distance_normalized": distance,
                "outbound_overlap": overlap,
                "balance_delta": balance_delta,
                "estimated_bays": estimated_bays,
                "height_conflicts": sum(conflict_by_period.values()),
                "time_weighted_height_conflict": weighted_height_conflict,
                "stability_loss": stability_loss,
                "released_quantity": released_quantity,
                "residual_capacity_basis": capacity_basis,
            }
    return scores


def _pair_resource_features(d: dict, scores: dict) -> dict[Pair, dict]:
    count = max(2, math.ceil(len(d["blocks"]) * DEPENDENCY_CANDIDATE_BLOCK_RATIO))
    features = {}
    old_totals = _pair_totals(d["previous_reservation"])
    for pair in sorted(_dependency_pairs(d)):
        j, g = pair
        ranked = sorted(d["blocks"], key=lambda k: (-scores[j, g, k]["score"], k))
        old_blocks = existing_blocks(d, j, g)
        eligible = {
            k for k in d["blocks"]
            if scores[j, g, k]["compatible_capacity"] > 0 or k in old_blocks
        }
        demand = d["remaining_demand"].get(pair, 0)
        candidates = (
            old_blocks if demand <= 0 else set(ranked[:count]) | old_blocks
        ) & eligible
        profile, weights = _pair_time_profile(d, pair)
        features[pair] = {
            "demand": demand,
            "released_quantity": max(0, old_totals.get(pair, 0) - demand),
            "size": d["group_attrs"][g]["size"],
            "height": d["group_attrs"][g]["height"],
            "arrival_profile": tuple(profile[n] for n in d["periods"]),
            "arrival_weight": tuple(weights[n] for n in d["periods"]),
            "old_blocks": old_blocks,
            "eligible_blocks": eligible,
            "candidate_blocks": candidates,
            "compatible_capacity_by_block": {
                k: scores[j, g, k]["compatible_capacity"] for k in d["blocks"]
            },
            "compatible_capacity_by_block_period": {
                (k, n): scores[j, g, k]["capacity_by_period"][n]
                for k in d["blocks"] for n in d["periods"]
            },
        }
    return features


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cosine(a: tuple, b: tuple) -> float:
    norm_a = math.sqrt(sum(value * value for value in a))
    norm_b = math.sqrt(sum(value * value for value in b))
    if not norm_a or not norm_b:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


def _build_dependency_graph(d: dict, scores: dict) -> tuple[dict, list[dict], dict]:
    """Build a deterministic pure-Python resource competition graph."""
    resource = _pair_resource_features(d, scores)
    graph = {pair: [] for pair in resource}
    edges = []
    pairs = sorted(resource)
    for index, pair_a in enumerate(pairs):
        a = resource[pair_a]
        for pair_b in pairs[index + 1:]:
            b = resource[pair_b]
            if a["size"] != b["size"]:
                continue
            common = a["candidate_blocks"] & b["candidate_blocks"]
            if not common:
                continue
            candidate_overlap = _jaccard(a["candidate_blocks"], b["candidate_blocks"])
            temporal_overlap = _cosine(a["arrival_profile"], b["arrival_profile"])
            common_capacity = sum(
                min(a["arrival_weight"][index], b["arrival_weight"][index])
                * min(
                    a["compatible_capacity_by_block_period"][k, period],
                    b["compatible_capacity_by_block_period"][k, period],
                )
                for k in common
                for index, period in enumerate(d["periods"])
            )
            resource_quantity = (
                a["demand"] + a["released_quantity"]
                + b["demand"] + b["released_quantity"]
            )
            capacity_pressure = min(1.0, resource_quantity / max(1, common_capacity))
            historical_overlap = _jaccard(a["old_blocks"], b["old_blocks"])
            fragmentation = 1.0 if a["height"] != b["height"] else .8
            dependency = fragmentation * (
                DEPENDENCY_WEIGHT_CANDIDATE_OVERLAP * candidate_overlap
                + DEPENDENCY_WEIGHT_TEMPORAL_OVERLAP * temporal_overlap
                + DEPENDENCY_WEIGHT_CAPACITY_PRESSURE * capacity_pressure
                + DEPENDENCY_WEIGHT_HISTORICAL_OVERLAP * historical_overlap
            )
            if dependency <= 0:
                continue
            graph[pair_a].append((pair_b, dependency))
            graph[pair_b].append((pair_a, dependency))
            edges.append({
                "pair_a": list(pair_a),
                "pair_b": list(pair_b),
                "dependency_score": dependency,
                "candidate_overlap": candidate_overlap,
                "temporal_overlap": temporal_overlap,
                "capacity_pressure": capacity_pressure,
                "common_time_weighted_capacity": common_capacity,
                "historical_overlap": historical_overlap,
                "fragmentation_factor": fragmentation,
            })
    for pair in graph:
        graph[pair].sort(key=lambda item: (-item[1], item[0]))
    edges.sort(key=lambda edge: (-edge["dependency_score"], tuple(edge["pair_a"]), tuple(edge["pair_b"])))
    return graph, edges, resource


def _propagate_impact_pairs(
    direct_pairs: set[Pair],
    dependency_graph: dict,
    *,
    impact_direction: dict[Pair, str] | None = None,
    edge_threshold: float = DEPENDENCY_EDGE_THRESHOLD,
    path_threshold: float = DEPENDENCY_PATH_THRESHOLD,
    max_depth: int = DEPENDENCY_MAX_DEPTH,
    decay: float = DEPENDENCY_DECAY,
    max_neighbors: int = DEPENDENCY_MAX_NEIGHBORS_PER_PAIR,
) -> dict:
    """Propagate impact along the strongest finite-depth dependency paths."""
    best = {pair: 1.0 for pair in sorted(direct_pairs)}
    depth = {pair: 0 for pair in sorted(direct_pairs)}
    parent = {pair: None for pair in sorted(direct_pairs)}
    incoming_edge = {pair: 1.0 for pair in sorted(direct_pairs)}
    propagation_type = {
        pair: "release_opportunity"
        if (impact_direction or {}).get(pair) in ("decrease", "disappear")
        else "pressure"
        for pair in sorted(direct_pairs)
    }
    queue = deque(sorted(direct_pairs))
    while queue:
        current = queue.popleft()
        if depth[current] >= max_depth:
            continue
        neighbors = [item for item in dependency_graph.get(current, ()) if item[1] >= edge_threshold]
        for neighbor, edge_score in neighbors[:max_neighbors]:
            score = best[current] * edge_score * decay
            candidate_depth = depth[current] + 1
            if score < path_threshold:
                continue
            if score > best.get(neighbor, -1) + 1e-12:
                best[neighbor] = score
                depth[neighbor] = candidate_depth
                parent[neighbor] = current
                incoming_edge[neighbor] = edge_score
                propagation_type[neighbor] = propagation_type[current]
                queue.append(neighbor)
    affected = set(best)
    return {
        "direct_pairs": set(direct_pairs),
        "propagated_pairs": affected - set(direct_pairs),
        "affected_pairs": affected,
        "best_path_score": best,
        "propagation_depth": depth,
        "parent_pair": parent,
        "edge_score": incoming_edge,
        "propagation_type": propagation_type,
    }


def _allowed(
    d: dict,
    level: int,
    direct_pairs: set[Pair],
    propagated_pairs: set[Pair],
    scores: dict,
    repair_pairs: set[Pair] | None = None,
    release_opportunity_blocks: dict[Pair, set[str]] | None = None,
) -> dict:
    result = {}
    repair_pairs = set(repair_pairs or ())
    release_opportunity_blocks = release_opportunity_blocks or {}
    affected = direct_pairs | propagated_pairs
    for pair in sorted(d["remaining_demand"]):
        j, g = pair
        old_blocks = existing_blocks(d, j, g)
        ranked = sorted(d["blocks"], key=lambda k: (-scores[j, g, k]["score"], k))
        batch = max(1, math.ceil(len(d["blocks"]) * ADAPTIVE_BLOCK_BATCH_RATIO))
        if level == 3:
            selected = set(d["blocks"])
        elif pair in direct_pairs:
            base = 1 if old_blocks else 2
            extra = (batch * level) if pair in repair_pairs else 0
            selected = old_blocks | set(ranked[:min(len(ranked), base + extra)])
        elif pair in propagated_pairs:
            extra = (batch * level) if pair in repair_pairs else 0
            selected = (
                old_blocks
                | release_opportunity_blocks.get(pair, set())
                | set(ranked[:min(len(ranked), 1 + extra)])
            )
        elif old_blocks:
            selected = old_blocks
        else:
            raise ValueError(f"positive-demand unaffected pair without history: {pair}")
        result[pair] = [
            i for i in d["bays"] if d["bay_block"][i] in selected and compatible(d, i, g)
        ]
        if pair in affected and not result[pair]:
            raise ValueError(f"affected pair has no compatible candidate bay: {pair}")
    return result


def _solution_residual_capacity(
    d: dict,
    solution: dict,
) -> tuple[dict[tuple[str, int], float], dict[tuple[str, int], set[str]]]:
    """Reconstruct bay-period spare capacity and occupied heights after a plan."""
    residual: dict[tuple[str, int], float] = {}
    occupied_heights: dict[tuple[str, int], set[str]] = {}
    attrs = d["group_attrs"]
    planned_flow = solution.get("din", {})
    locked_by_bay: dict[str, list[tuple[str, float, str | None]]] = defaultdict(list)
    for (bay, old_ship), quantity in d["locked_inventory"].items():
        locked_by_bay[bay].append((
            old_ship,
            quantity,
            d["locked_height"].get((bay, old_ship)),
        ))
    actual_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (bay, ship, group), quantity in d["actual_inventory"].items():
        actual_by_bay[bay].append((ship, group, quantity))
    planned_by_bay: dict[
        str, list[tuple[str, str, int, float]]
    ] = defaultdict(list)
    for (bay, ship, group, arrival), quantity in planned_flow.items():
        planned_by_bay[bay].append((ship, group, arrival, quantity))
    relevant_ships = {
        ship
        for entries in actual_by_bay.values()
        for ship, _group, _quantity in entries
    } | {
        ship
        for entries in planned_by_bay.values()
        for ship, _group, _arrival, _quantity in entries
    }
    presence = {
        (ship, period): ship_present_at(d, ship, period)
        for ship in relevant_ships
        for period in d["periods"]
    }
    for bay in d["bays"]:
        locked_entries = locked_by_bay[bay]
        actual_entries = actual_by_bay[bay]
        planned_entries = planned_by_bay[bay]
        for period in d["periods"]:
            locked = sum(
                quantity
                for old_ship, quantity, _height in locked_entries
                if d["locked_release_local"].get((bay, old_ship), INF) > period
            )
            actual = sum(
                quantity
                for ship, _group, quantity in actual_entries
                if presence[ship, period]
            )
            planned = sum(
                quantity
                for ship, _group, arrival, quantity in planned_entries
                if arrival <= period and presence[ship, period]
            )
            residual[bay, period] = max(
                0.0,
                float(d["capacity"][bay] - locked - actual - planned),
            )
            heights = {
                height
                for old_ship, _quantity, height in locked_entries
                if height is not None
                and d["locked_release_local"].get((bay, old_ship), INF) > period
            }
            heights |= {
                attrs[group]["height"]
                for ship, group, quantity in actual_entries
                if quantity > 1e-6 and presence[ship, period]
            }
            heights |= {
                attrs[group]["height"]
                for ship, group, arrival, quantity in planned_entries
                if arrival <= period
                and quantity > 1e-6
                and presence[ship, period]
            }
            occupied_heights[bay, period] = heights
    return residual, occupied_heights


def _bottleneck_minimal_expansion(
    d: dict,
    current_allowed: dict,
    solution: dict,
    shortage_pairs: set[Pair],
    scores: dict,
    *,
    time_limit: float,
    seed: int,
) -> tuple[dict, dict]:
    """Select a minimum set of added pair-block domains covering shortage."""
    selector_started = time.perf_counter()
    allowed = {pair: list(bays) for pair, bays in current_allowed.items()}
    residual, occupied_heights = _solution_residual_capacity(d, solution)
    attrs = d["group_attrs"]
    compatible_bays_by_group_block = {
        (group, block): tuple(
            bay
            for bay in d["bays_in_block"][block]
            if compatible(d, bay, group)
        )
        for group in {pair[1] for pair in shortage_pairs}
        for block in d["blocks"]
    }
    deficits: dict[tuple[Pair, int], float] = {}
    for pair in sorted(shortage_pairs):
        ship, group = pair
        cumulative = 0.0
        for period in d["periods"]:
            cumulative += float(solution["shortage"].get((ship, group, period), 0))
            deficits[pair, period] = cumulative if ship_present_at(d, ship, period) else 0.0

    current_blocks = {
        pair: {d["bay_block"][bay] for bay in allowed.get(pair, ())}
        for pair in shortage_pairs
    }
    ranked_blocks = {
        pair: sorted(
            d["blocks"],
            key=lambda block: (-scores[pair[0], pair[1], block]["score"], block),
        )
        for pair in shortage_pairs
    }
    rank = {
        (pair, block): position + 1
        for pair in shortage_pairs
        for position, block in enumerate(ranked_blocks[pair])
    }
    capacity: dict[tuple[Pair, str, int], float] = {}
    candidate_keys: set[tuple[Pair, str]] = set()
    for pair in sorted(shortage_pairs):
        _ship, group = pair
        target_height = attrs[group]["height"]
        for block in d["blocks"]:
            if block in current_blocks[pair]:
                continue
            for period in d["periods"]:
                value = sum(
                    residual[bay, period]
                    for bay in compatible_bays_by_group_block[group, block]
                    if (
                        not occupied_heights[bay, period]
                        or target_height in occupied_heights[bay, period]
                    )
                )
                capacity[pair, block, period] = value
            if any(
                capacity[pair, block, period] > 1e-6
                and deficits[pair, period] > 1e-6
                for period in d["periods"]
            ):
                candidate_keys.add((pair, block))

    diagnostics = {
        "selector": "granularity_guarded_minimum_pair_block_cover",
        "shortage_pairs": [list(pair) for pair in sorted(shortage_pairs)],
        "deficit_by_pair_period": {
            f"{pair[0]}|{pair[1]}|{period}": value
            for (pair, period), value in sorted(deficits.items())
            if value > 1e-6
        },
        "candidate_pair_block_count": len(candidate_keys),
        "selected_pair_blocks": {},
        "granularity_guard_pair_blocks": {},
        "selected_pair_block_count": 0,
        "selector_runtime": 0.0,
        "status": "not_run",
    }
    if not candidate_keys or not any(value > 1e-6 for value in deficits.values()):
        diagnostics["status"] = "no_cover_candidates"
        return allowed, diagnostics

    model = gp.Model("bottleneck_minimal_expansion")
    model.Params.OutputFlag = 0
    model.Params.Threads = 1
    model.Params.Seed = seed
    model.Params.TimeLimit = max(.01, time_limit)
    z_keys = sorted(
        (pair[0], pair[1], block) for pair, block in candidate_keys
    )
    z = model.addVars(z_keys, vtype=GRB.BINARY, name="open_block")
    take_keys = sorted(
        (pair[0], pair[1], block, period)
        for pair, block in candidate_keys
        for period in d["periods"]
        if capacity[pair, block, period] > 1e-6
        and deficits[pair, period] > 1e-6
    )
    take = model.addVars(take_keys, lb=0.0, name="covered_capacity")
    take_by_pair_period: dict[
        tuple[str, str, int], list
    ] = defaultdict(list)
    take_by_block_period_size: dict[
        tuple[str, int, int], list
    ] = defaultdict(list)
    for ship, group, block, period in take_keys:
        variable = take[ship, group, block, period]
        take_by_pair_period[ship, group, period].append(variable)
        take_by_block_period_size[
            block, period, attrs[group]["size"]
        ].append(variable)
        pair = (ship, group)
        model.addConstr(
            variable
            <= capacity[pair, block, period] * z[ship, group, block]
        )
    for pair in sorted(shortage_pairs):
        ship, group = pair
        for period in d["periods"]:
            deficit = deficits[pair, period]
            if deficit <= 1e-6:
                continue
            terms = take_by_pair_period[ship, group, period]
            model.addConstr(gp.quicksum(terms) >= deficit)
    for block in d["blocks"]:
        for period in d["periods"]:
            for size in sorted({attrs[pair[1]]["size"] for pair in shortage_pairs}):
                terms = take_by_block_period_size[block, period, size]
                if not terms:
                    continue
                block_residual = sum(
                    residual[bay, period]
                    for bay in d["bays_in_block"][block]
                    if d["bay_size"][bay] == size
                )
                model.addConstr(gp.quicksum(terms) <= block_residual)

    maximum_rank_sum = max(1, len(candidate_keys) * len(d["blocks"]))
    model.setObjective(
        gp.quicksum(
            (maximum_rank_sum + rank[pair, block])
            * z[pair[0], pair[1], block]
            for pair, block in candidate_keys
        ),
        GRB.MINIMIZE,
    )
    elapsed_before_optimize = time.perf_counter() - selector_started
    remaining_time = time_limit - elapsed_before_optimize
    if remaining_time <= 0:
        diagnostics["status"] = "selector_budget_exhausted_before_optimize"
        diagnostics["selector_runtime"] = elapsed_before_optimize
        model.dispose()
        return allowed, diagnostics
    model.Params.TimeLimit = max(.01, remaining_time)
    started = time.perf_counter()
    model.optimize()
    diagnostics["selector_runtime"] = time.perf_counter() - started
    diagnostics["solver_status"] = int(model.Status)
    diagnostics["status"] = "cover_found" if model.SolCount else "cover_not_found"
    selected = {
        (pair, block)
        for pair, block in candidate_keys
        if model.SolCount and z[pair[0], pair[1], block].X > .5
    }
    model.dispose()
    if not selected:
        return allowed, diagnostics

    guard_additions: set[tuple[Pair, str]] = set()
    for pair in sorted(shortage_pairs):
        pair_selected = {
            block for selected_pair, block in selected if selected_pair == pair
        }
        if not pair_selected:
            continue
        positive_periods = [
            period
            for period in d["periods"]
            if deficits[pair, period] > 1e-6
        ]
        minimum_surplus = min(
            (
                sum(capacity[pair, block, period] for block in pair_selected)
                - deficits[pair, period]
                for period in positive_periods
            ),
            default=0.0,
        )
        group = pair[1]
        bay_granularity = max(
            (
                d["capacity"][bay]
                for bay in d["bays"]
                if compatible(d, bay, group)
            ),
            default=0.0,
        )
        if minimum_surplus + 1e-6 >= bay_granularity:
            continue
        backup = next(
            (
                block
                for block in ranked_blocks[pair]
                if (pair, block) in candidate_keys
                and block not in pair_selected
            ),
            None,
        )
        if backup is not None:
            guard_additions.add((pair, backup))
    selected |= guard_additions

    selected_by_pair: dict[Pair, list[str]] = {}
    for pair, block in sorted(selected):
        selected_by_pair.setdefault(pair, []).append(block)
        ship, group = pair
        allowed[ship, group] = sorted(set(allowed[ship, group]) | {
            bay
            for bay in d["bays_in_block"][block]
            if compatible(d, bay, group)
        })
    diagnostics["selected_pair_blocks"] = {
        f"{pair[0]}|{pair[1]}": blocks
        for pair, blocks in sorted(selected_by_pair.items())
    }
    guard_by_pair: dict[Pair, list[str]] = {}
    for pair, block in sorted(guard_additions):
        guard_by_pair.setdefault(pair, []).append(block)
    diagnostics["granularity_guard_pair_blocks"] = {
        f"{pair[0]}|{pair[1]}": blocks
        for pair, blocks in sorted(guard_by_pair.items())
    }
    diagnostics["granularity_guard_pair_block_count"] = len(guard_additions)
    diagnostics["selected_pair_block_count"] = len(selected)
    return allowed, diagnostics


def _horizon_end_block_utilization(d: dict, reservation: dict) -> dict[str, float]:
    """Return end-of-horizon occupancy utilization on the model's definition."""
    last = d["periods"][-1]
    result: dict[str, float] = {}
    for block in d["blocks"]:
        occupancy = sum(
            quantity
            for (bay, old_ship), quantity in d["locked_inventory"].items()
            if d["bay_block"][bay] == block
            and d["locked_release_local"].get((bay, old_ship), INF) > last
        ) + sum(
            quantity
            for (bay, ship, _group), quantity in d["actual_inventory"].items()
            if d["bay_block"][bay] == block and ship_present_at(d, ship, last)
        ) + sum(
            quantity
            for (bay, ship, _group), quantity in reservation.items()
            if d["bay_block"][bay] == block and ship_present_at(d, ship, last)
        )
        block_capacity = sum(
            d["capacity"][bay] for bay in d["bays_in_block"][block]
        )
        result[block] = occupancy / max(1, block_capacity)
    return result


def _quality_polish_allowed(
    d: dict,
    affected_pairs: set[Pair],
    direct_pairs: set[Pair],
    propagated_pairs: set[Pair],
    scores: dict,
    solution: dict,
    release_opportunity_blocks: dict[Pair, set[str]] | None = None,
) -> tuple[dict, dict]:
    allowed = _allowed(
        d,
        0,
        direct_pairs,
        propagated_pairs,
        scores,
        release_opportunity_blocks=release_opportunity_blocks,
    )
    reserve, din, attrs = solution["reservation"], solution["din"], d["group_attrs"]
    max_dist = max(d["distance"].values(), default=1)
    max_out = max(d["forecast_outbound"].values(), default=1)
    final_utilization = _horizon_end_block_utilization(d, reserve)
    average_utilization = sum(final_utilization.values()) / max(
        1, len(final_utilization)
    )
    contribution = {}
    support_baseline = existing_support(d, period=0)
    for j, g in sorted(affected_pairs & set(d["remaining_demand"])):
        demand = max(1, d["remaining_demand"][j, g])
        used = [i for (i, jj, gg), q in reserve.items() if jj == j and gg == g and q > 1e-6]
        pod = attrs[g]["pod"]
        support_bays = {
            bay for ship, existing_pod, bay in support_baseline
            if ship == j and existing_pod == pod
        } | {
            bay
            for (bay, ship, group), quantity in reserve.items()
            if ship == j and attrs[group]["pod"] == pod and quantity > 1e-6
        }
        support = len(support_bays) / max(1, len(d["bays"]))
        distance = sum(
            d["distance"][j, d["bay_block"][i]] * q
            for (i, jj, gg, _n), q in din.items() if jj == j and gg == g
        ) / (demand * max_dist)
        overlap = sum(
            d["forecast_outbound"].get((d["bay_block"][i], n), 0) * q
            for (i, jj, gg, n), q in din.items() if jj == j and gg == g
        ) / (demand * max_out)
        overload = sum(
            max(
                0,
                final_utilization[d["bay_block"][i]] - average_utilization,
            ) * q
            for (i, jj, gg), q in reserve.items() if jj == j and gg == g
        ) / demand
        contribution[j, g] = (
            QUALITY_POLISH_WEIGHT_SUPPORT * support
            + QUALITY_POLISH_WEIGHT_DISTANCE * distance
            + QUALITY_POLISH_WEIGHT_OVERLAP * overlap
            + QUALITY_POLISH_WEIGHT_UTILIZATION * overload
        )
    count = max(1, math.ceil(QUALITY_POLISH_PAIR_RATIO * len(contribution))) if contribution else 0
    selected = set(sorted(contribution, key=lambda pair: (-contribution[pair], pair))[:count])
    expanded = {}
    for j, g in sorted(selected):
        current_blocks = {d["bay_block"][i] for i in allowed[j, g]}
        alternatives = [
            k for k in sorted(d["blocks"], key=lambda k: (-scores[j, g, k]["score"], k))
            if k not in current_blocks
        ]
        additions = alternatives[:QUALITY_POLISH_BLOCKS_PER_PAIR]
        if additions:
            allowed[j, g] = sorted(set(allowed[j, g]) | {
                i for k in additions for i in d["bays_in_block"][k] if compatible(d, i, g)
            })
            expanded[j, g] = additions
    return allowed, {
        "selected_pairs": [list(pair) for pair in sorted(selected)],
        "expanded_blocks": {f"{j}|{g}": blocks for (j, g), blocks in sorted(expanded.items())},
        "selection_ratio": QUALITY_POLISH_PAIR_RATIO,
        "blocks_per_selected_pair": QUALITY_POLISH_BLOCKS_PER_PAIR,
        "utilization_definition": "horizon_end_occupancy_over_block_capacity",
        "contribution_weights": {
            "support": QUALITY_POLISH_WEIGHT_SUPPORT,
            "distance": QUALITY_POLISH_WEIGHT_DISTANCE,
            "overlap": QUALITY_POLISH_WEIGHT_OVERLAP,
            "utilization": QUALITY_POLISH_WEIGHT_UTILIZATION,
        },
    }


def _submit_start(
    variables: dict,
    d: dict,
    incumbent: dict | None = None,
    enabled: bool = True,
) -> dict:
    """Submit a conservation-complete integer MIP start.

    A shifted previous plan may exceed a revised period forecast.  Retain its
    compatible flow deterministically up to the new forecast, derive matching
    reservation totals, and send the residual forecast to shortage.  This is
    always a feasible arrival-conservation start; Gurobi only has to complete
    continuous accounting auxiliaries.
    """
    if not enabled:
        return {"submitted": False, "source": "disabled", "nonzero_values": 0, "covered_variables": 0}
    source = (incumbent or {}).get("reservation", d["previous_reservation"])
    flows = (incumbent or {}).get("din", d.get("previous_din", {}))
    raw_flow_by_arrival: dict[
        tuple[str, str, int], list[tuple[tuple[str, str, str, int], int]]
    ] = defaultdict(list)
    covered = 0
    for key in variables["din"]:
        value = max(0, int(round(float(flows.get(key, 0)))))
        raw_flow_by_arrival[key[1], key[2], key[3]].append((key, value))
        covered += int(key in flows)
    source_flow_quantity = sum(
        value
        for entries in raw_flow_by_arrival.values()
        for _key, value in entries
    )
    if source_flow_quantity <= 0:
        return {
            "submitted": False,
            "source": "no_positive_previous_flow",
            "nonzero_values": 0,
            "covered_variables": covered,
            "structural_start_values": 0,
            "total_start_variables": (
                len(variables["reservation"]) + len(variables["din"])
            ),
            "coverage": 0.0,
            "forecast_shortage_start": 0,
            "clipped_previous_flow": 0,
        }

    clipped_flow: dict[tuple[str, str, str, int], int] = {}
    clipped_quantity = 0
    for arrival_key, entries in raw_flow_by_arrival.items():
        remaining = max(
            0,
            int(round(float(d["forecast_arrivals"].get(arrival_key, 0)))),
        )
        for key, requested in sorted(entries):
            retained = min(requested, remaining)
            clipped_flow[key] = retained
            remaining -= retained
            clipped_quantity += requested - retained

    reservation_start: dict[tuple[str, str, str], int] = defaultdict(int)
    arrival_flow: dict[tuple[str, str, int], int] = defaultdict(int)
    share_start: dict[tuple[str, str, str, int], int] = defaultdict(int)
    for (bay, ship, group, period), value in clipped_flow.items():
        variables["din"][bay, ship, group, period].Start = value
        reservation_start[bay, ship, group] += value
        arrival_flow[ship, group, period] += value
        share_start[ship, d["bay_block"][bay], group, period] += value

    nonzero = 0
    for key, variable in variables["reservation"].items():
        value = reservation_start[key]
        variable.Start = value
        covered += int(key in source)
        nonzero += int(value > 0)
    nonzero += sum(value > 0 for value in clipped_flow.values())

    total_shortage = 0
    for key, variable in variables.get("shortage", {}).items():
        value = max(
            0,
            int(round(float(d["forecast_arrivals"].get(key, 0))))
            - arrival_flow[key],
        )
        variable.Start = value
        total_shortage += value

    attrs = d["group_attrs"]
    active_support = {
        (ship, attrs[group]["pod"], bay)
        for (bay, ship, group), value in reservation_start.items()
        if value > 0
    }
    prior_support = existing_support(d, period=0)
    for key, variable in variables.get("pod_bay_use", {}).items():
        variable.Start = int(key in active_support)
    for key, variable in variables.get("new_bay", {}).items():
        variable.Start = int(key in active_support and key not in prior_support)

    occupied_height: set[tuple[str, int, str]] = set()
    for (bay, old_ship), height in d["locked_height"].items():
        release = d["locked_release_local"].get((bay, old_ship), INF)
        occupied_height.update(
            (bay, period, height)
            for period in d["periods"]
            if release > period
        )
    for (bay, ship, group), value in d["actual_inventory"].items():
        if value > 0:
            occupied_height.update(
                (bay, period, attrs[group]["height"])
                for period in d["periods"]
                if ship_present_at(d, ship, period)
            )
    for (bay, ship, group, arrival), value in clipped_flow.items():
        if value > 0:
            occupied_height.update(
                (bay, period, attrs[group]["height"])
                for period in d["periods"]
                if arrival <= period and ship_present_at(d, ship, period)
            )
    for key, variable in variables.get("bay_height", {}).items():
        variable.Start = int(key in occupied_height)

    for key, variable in variables.get("cancel", {}).items():
        variable.Start = max(
            0,
            int(round(float(d["previous_reservation"].get(key, 0))))
            - reservation_start[key],
        )
    for key, variable in variables.get("in_share", {}).items():
        variable.Start = share_start[key]

    structural = 0
    if incumbent:
        for name, group in variables.items():
            if name in {
                "reservation",
                "din",
                "shortage",
                "pod_bay_use",
                "bay_height",
                "cancel",
                "new_bay",
                "in_share",
            }:
                continue
            values = incumbent.get(name, {})
            for key, variable in group.items():
                if key in values:
                    variable.Start = float(values[key]);structural += 1
    total = len(variables["reservation"]) + len(variables["din"])
    return {
        "submitted": True,
        "source": "previous_stage" if incumbent else "previous_cycle",
        "nonzero_values": nonzero,
        "covered_variables": covered,
        "structural_start_values": structural,
        "total_start_variables": total,
        "coverage": covered / max(1, total),
        "forecast_shortage_start": total_shortage,
        "clipped_previous_flow": clipped_quantity,
    }


def canonical_stability_metrics(d: dict, reservation: dict, shortage: dict) -> dict:
    """Compute pair-level plan revisions without cross-pair shortage offsets."""
    old = d["previous_reservation"]
    old_totals, current_totals = _pair_totals(old), d["remaining_demand"]
    pairs = set(old_totals) | set(current_totals)
    old_entries_by_pair: dict[Pair, list[tuple[str, float]]] = defaultdict(list)
    old_blocks: dict[tuple[str, str, str], float] = defaultdict(float)
    current_blocks: dict[tuple[str, str, str], float] = defaultdict(float)
    shortage_totals: dict[Pair, float] = defaultdict(float)
    for (bay, ship, group), quantity in old.items():
        old_entries_by_pair[ship, group].append((bay, quantity))
        old_blocks[ship, group, d["bay_block"][bay]] += quantity
    for (bay, ship, group), quantity in reservation.items():
        current_blocks[ship, group, d["bay_block"][bay]] += quantity
    for (ship, group, _period), quantity in shortage.items():
        shortage_totals[ship, group] += quantity
    pair_cancellation: dict[Pair, float] = {}
    pair_discretionary: dict[Pair, float] = {}
    pair_reallocation: dict[Pair, float] = {}
    mandatory_by_pair: dict[Pair, float] = {}
    for j, g in pairs:
        pair = (j, g)
        cancellation = sum(
            max(0, quantity - reservation.get((bay, j, g), 0))
            for bay, quantity in old_entries_by_pair[pair]
        )
        mandatory = max(0, old_totals.get(pair, 0) - current_totals.get(pair, 0))
        pair_shortage = shortage_totals[pair]
        block_cancel = sum(
            max(
                0,
                old_blocks[j, g, block] - current_blocks[j, g, block],
            )
            for block in d["blocks"]
        )
        pair_cancellation[pair] = cancellation
        mandatory_by_pair[pair] = mandatory
        pair_discretionary[pair] = max(0, cancellation - mandatory - pair_shortage)
        pair_reallocation[pair] = max(0, block_cancel - mandatory - pair_shortage)
    cancellation_total = sum(pair_cancellation.values())
    mandatory_total = sum(mandatory_by_pair.values())
    discretionary_total = sum(pair_discretionary.values())
    block_reallocation = sum(pair_reallocation.values())
    attrs = d["group_attrs"]
    old_support = existing_support(d, period=0)
    support = {(j, attrs[g]["pod"], i) for (i, j, g), q in reservation.items() if q > 1e-6}
    new_bays = len(support - old_support)
    stability_cost = (
        STABILITY_CANCEL_WEIGHT * cancellation_total
        + STABILITY_NEW_BAY_WEIGHT * new_bays
        + STABILITY_BLOCK_REALLOCATION_WEIGHT * block_reallocation
    )
    return {
        "cancellation_quantity": float(cancellation_total),
        "mandatory_reduction": float(mandatory_total),
        "discretionary_cancel": float(discretionary_total),
        "new_bay_count": float(new_bays),
        "block_reallocation_quantity": float(block_reallocation),
        "stability_cost": float(stability_cost),
        "pair_discretionary_cancel": {
            pair: float(value) for pair, value in sorted(pair_discretionary.items()) if value > 1e-9
        },
        "pair_block_reallocation": {
            pair: float(value) for pair, value in sorted(pair_reallocation.items()) if value > 1e-9
        },
        "pair_cancellation": {
            pair: float(value) for pair, value in sorted(pair_cancellation.items()) if value > 1e-9
        },
    }


_OPERATION_ACCOUNTING_FIELDS = (
    "concentration_raw",
    "occupancy_balance_raw",
    "distance_raw",
    "in_out_conflict_raw",
    "concentration_normalized",
    "occupancy_balance_normalized",
    "distance_normalized",
    "in_out_conflict_normalized",
    "concentration_weight",
    "occupancy_balance_weight",
    "distance_weight",
    "in_out_conflict_weight",
    "concentration_weighted",
    "occupancy_balance_weighted",
    "distance_weighted",
    "in_out_conflict_weighted",
    "normalized_operations_score",
    "concentration_scale",
    "occupancy_balance_scale",
    "distance_scale",
    "in_out_conflict_scale",
)


def _record_operation_accounting(
    d: dict,
    solution: dict,
    record,
    *,
    operation_weights: Mapping[str, float] | None,
) -> None:
    """Cross-check objective expressions and indicators from physical flows."""
    components = solution.get("components", {})
    expected = evaluate_operation_components(
        d,
        solution["reservation"],
        solution["din"],
        operation_weights=operation_weights,
    )
    missing_components = [
        name for name in _OPERATION_ACCOUNTING_FIELDS if name not in components
    ]
    record("operation_component_missing", len(missing_components))
    for name in _OPERATION_ACCOUNTING_FIELDS:
        if name in components:
            record(
                f"{name}_accounting",
                abs(float(components[name]) - expected[name]),
            )

    support = reservation_support(d, solution["reservation"])
    record("pod_bay_use_missing", int("pod_bay_use" not in solution))
    if "pod_bay_use" in solution:
        actual_use = solution["pod_bay_use"]
        for key in set(actual_use) | support:
            record(
                "pod_bay_use_accounting",
                abs(float(actual_use.get(key, 0)) - float(key in support)),
            )
    record("new_bay_indicator_missing", int("new_bay" not in solution))
    if "new_bay" in solution:
        expected_new = support - existing_support(d, period=0)
        actual_new = solution["new_bay"]
        for key in set(actual_new) | expected_new:
            record(
                "new_bay_indicator_accounting",
                abs(float(actual_new.get(key, 0)) - float(key in expected_new)),
            )


def _validate_rolling_solution_reference(
    d: dict,
    solution: dict,
    tol: float = 1e-6,
    *,
    operation_weights: Mapping[str, float] | None = None,
) -> dict:
    """Original scan-based validator retained as an equivalence oracle."""

    reserve, din, inv = solution["reservation"], solution["din"], solution["inventory"]
    shortage, attrs, violations = solution["shortage"], d["group_attrs"], {}

    def record(name: str, value: float) -> None:
        violations[name] = max(violations.get(name, 0), max(0, float(value)))

    reserve_by_pair: dict[Pair, float] = defaultdict(float)
    reserve_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (bay, ship, group), quantity in reserve.items():
        reserve_by_pair[ship, group] += quantity
        reserve_by_bay[bay].append((ship, group, quantity))

    din_by_pair: dict[Pair, float] = defaultdict(float)
    din_by_pair_period: dict[tuple[str, str, int], float] = defaultdict(float)
    din_by_bay: dict[str, list[tuple[str, str, int, float]]] = defaultdict(list)
    din_by_bay_pair: dict[
        tuple[str, str, str], list[tuple[int, float]]
    ] = defaultdict(list)
    for (bay, ship, group, period), quantity in din.items():
        din_by_pair[ship, group] += quantity
        din_by_pair_period[ship, group, period] += quantity
        din_by_bay[bay].append((ship, group, period, quantity))
        din_by_bay_pair[bay, ship, group].append((period, quantity))

    locked_by_bay: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (bay, old_ship), quantity in d["locked_inventory"].items():
        locked_by_bay[bay].append((old_ship, quantity))
    locked_height_by_bay: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (bay, old_ship), height in d["locked_height"].items():
        locked_height_by_bay[bay].append((old_ship, height))
    actual_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (bay, ship, group), quantity in d["actual_inventory"].items():
        actual_by_bay[bay].append((ship, group, quantity))

    for (j, g, n), forecast in d["forecast_arrivals"].items():
        placed = din_by_pair_period[j, g, n]
        record("period_arrival", abs(placed + shortage.get((j, g, n), 0) - forecast))
    for j, g in d["remaining_demand"]:
        record("reserve_flow", abs(reserve_by_pair[j, g] - din_by_pair[j, g]))
    last = d["periods"][-1]
    for i in d["bays"]:
        locked_final = sum(
            quantity
            for old_ship, quantity in locked_by_bay[i]
            if d["locked_release_local"].get((i, old_ship), INF) > last
        )
        actual_final = sum(
            quantity
            for ship, _group, quantity in actual_by_bay[i]
            if ship_present_at(d, ship, last)
        )
        planned_final = sum(
            quantity
            for ship, _group, quantity in reserve_by_bay[i]
            if ship_present_at(d, ship, last)
        )
        record("final_capacity", locked_final + actual_final + planned_final - d["capacity"][i])
        for n in d["periods"]:
            locked = sum(
                quantity
                for old_ship, quantity in locked_by_bay[i]
                if d["locked_release_local"].get((i, old_ship), INF) > n
            )
            actual = sum(
                quantity
                for ship, _group, quantity in actual_by_bay[i]
                if ship_present_at(d, ship, n)
            )
            planned = sum(
                quantity
                for ship, _group, period, quantity in din_by_bay[i]
                if period <= n and ship_present_at(d, ship, n)
            )
            record("period_capacity", locked + actual + planned - d["capacity"][i])
            used_heights = {
                height
                for old_ship, height in locked_height_by_bay[i]
                if d["locked_release_local"].get((i, old_ship), INF) > n
            }
            used_heights |= {
                attrs[group]["height"]
                for ship, group, quantity in actual_by_bay[i]
                if quantity > tol and ship_present_at(d, ship, n)
            }
            used_heights |= {
                attrs[group]["height"]
                for ship, group, period, quantity in din_by_bay[i]
                if period <= n
                and quantity > tol
                and ship_present_at(d, ship, n)
            }
            record("height", len(used_heights) - 1)
    for (i, _j, g), q in reserve.items():
        if q > tol:
            record("size", int(d["bay_size"][i] != attrs[g]["size"]))
        record("integrality", abs(q - round(q)))
    for (i, j, g, n), value in inv.items():
        cumulative = sum(
            quantity
            for period, quantity in din_by_bay_pair[i, j, g]
            if period <= n
        )
        expected = d["actual_inventory"].get((i, j, g), 0) + cumulative if ship_present_at(d, j, n) else 0
        record("inventory", abs(value - expected))
        if not ship_present_at(d, j, n):
            record("released_inventory", abs(value))
    for value in din.values():
        record("flow_integrality", abs(value - round(value)))
    canonical = canonical_stability_metrics(d, reserve, shortage)
    for name in (
        "cancellation_quantity",
        "mandatory_reduction",
        "discretionary_cancel",
        "new_bay_count",
        "block_reallocation_quantity",
        "stability_cost",
    ):
        expected = canonical[name]
        if name in solution.get("components", {}):
            record(f"{name}_accounting", abs(solution["components"][name] - expected))
    auxiliary_pairs = {
        "pair_cancellation": "pair_cancellation",
        "pair_discretionary_cancel": "pair_discretionary_cancel",
        "block_reallocation": "pair_block_reallocation",
    }
    stability_pairs = set(_dependency_pairs(d))
    for variable_name, canonical_name in auxiliary_pairs.items():
        actual_values = solution.get(variable_name, {})
        expected_values = canonical[canonical_name]
        for pair in stability_pairs:
            record(
                f"{variable_name}_accounting",
                abs(actual_values.get(pair, 0) - expected_values.get(pair, 0)),
            )
    _record_operation_accounting(
        d,
        solution,
        record,
        operation_weights=operation_weights,
    )
    maximum = max(violations.values(), default=0)
    return {"feasible": maximum <= tol, "max_violation": maximum, "violations": violations}


def validate_rolling_solution(
    d: dict,
    solution: dict,
    tol: float = 1e-6,
    *,
    operation_weights: Mapping[str, float] | None = None,
) -> dict:
    """Independently validate one solution with sparse cumulative indexes."""

    reserve = solution["reservation"]
    din = solution["din"]
    inv = solution["inventory"]
    shortage = solution["shortage"]
    attrs = d["group_attrs"]
    periods = tuple(d["periods"])
    last = periods[-1]
    violations: dict[str, float] = {}

    def record(name: str, value: float) -> None:
        violations[name] = max(
            violations.get(name, 0),
            max(0, float(value)),
        )

    presence_cache: dict[tuple[str, int], bool] = {}

    def present(ship: str, period: int) -> bool:
        key = (ship, period)
        if key not in presence_cache:
            presence_cache[key] = ship_present_at(d, ship, period)
        return presence_cache[key]

    reserve_by_pair: dict[Pair, float] = defaultdict(float)
    reserve_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (bay, ship, group), quantity in reserve.items():
        if quantity != 0:
            reserve_by_pair[ship, group] += quantity
            reserve_by_bay[bay].append((ship, group, quantity))

    din_by_pair: dict[Pair, float] = defaultdict(float)
    din_by_pair_period: dict[tuple[str, str, int], float] = defaultdict(float)
    din_period_quantity: dict[
        tuple[str, str, str],
        dict[int, float],
    ] = defaultdict(lambda: defaultdict(float))
    for (bay, ship, group, period), quantity in din.items():
        if quantity == 0:
            continue
        din_by_pair[ship, group] += quantity
        din_by_pair_period[ship, group, period] += quantity
        din_period_quantity[bay, ship, group][period] += quantity

    cumulative_din: dict[tuple[str, str, str, int], float] = {}
    planned_load: dict[tuple[str, int], float] = defaultdict(float)
    planned_heights: dict[tuple[str, int], set[str]] = defaultdict(set)
    for (bay, ship, group), by_period in din_period_quantity.items():
        cumulative = 0.0
        height_active = False
        for period in periods:
            period_quantity = by_period.get(period, 0.0)
            cumulative += period_quantity
            height_active = height_active or period_quantity > tol
            cumulative_din[bay, ship, group, period] = cumulative
            if present(ship, period):
                planned_load[bay, period] += cumulative
                if height_active:
                    planned_heights[bay, period].add(attrs[group]["height"])

    locked_load: dict[tuple[str, int], float] = defaultdict(float)
    locked_heights: dict[tuple[str, int], set[str]] = defaultdict(set)
    for (bay, old_ship), quantity in d["locked_inventory"].items():
        release = d["locked_release_local"].get((bay, old_ship), INF)
        for period in periods:
            if release > period:
                locked_load[bay, period] += quantity
    for (bay, old_ship), height in d["locked_height"].items():
        release = d["locked_release_local"].get((bay, old_ship), INF)
        for period in periods:
            if release > period:
                locked_heights[bay, period].add(height)

    actual_load: dict[tuple[str, int], float] = defaultdict(float)
    actual_heights: dict[tuple[str, int], set[str]] = defaultdict(set)
    for (bay, ship, group), quantity in d["actual_inventory"].items():
        for period in periods:
            if present(ship, period):
                actual_load[bay, period] += quantity
                if quantity > tol:
                    actual_heights[bay, period].add(attrs[group]["height"])

    for (ship, group, period), forecast in d["forecast_arrivals"].items():
        placed = din_by_pair_period[ship, group, period]
        record(
            "period_arrival",
            abs(placed + shortage.get((ship, group, period), 0) - forecast),
        )
    for ship, group in d["remaining_demand"]:
        record(
            "reserve_flow",
            abs(reserve_by_pair[ship, group] - din_by_pair[ship, group]),
        )

    for bay in d["bays"]:
        locked_final = locked_load[bay, last]
        actual_final = actual_load[bay, last]
        planned_final = sum(
            quantity
            for ship, _group, quantity in reserve_by_bay[bay]
            if present(ship, last)
        )
        record(
            "final_capacity",
            locked_final
            + actual_final
            + planned_final
            - d["capacity"][bay],
        )
        for period in periods:
            record(
                "period_capacity",
                locked_load[bay, period]
                + actual_load[bay, period]
                + planned_load[bay, period]
                - d["capacity"][bay],
            )
            used_heights = (
                locked_heights[bay, period]
                | actual_heights[bay, period]
                | planned_heights[bay, period]
            )
            record("height", len(used_heights) - 1)

    for (bay, _ship, group), quantity in reserve.items():
        if quantity > tol:
            record(
                "size",
                int(d["bay_size"][bay] != attrs[group]["size"]),
            )
        record("integrality", abs(quantity - round(quantity)))

    for (bay, ship, group, period), value in inv.items():
        expected = (
            d["actual_inventory"].get((bay, ship, group), 0)
            + cumulative_din.get((bay, ship, group, period), 0.0)
            if present(ship, period)
            else 0
        )
        record("inventory", abs(value - expected))
        if not present(ship, period):
            record("released_inventory", abs(value))

    for value in din.values():
        record("flow_integrality", abs(value - round(value)))

    canonical = canonical_stability_metrics(d, reserve, shortage)
    for name in (
        "cancellation_quantity",
        "mandatory_reduction",
        "discretionary_cancel",
        "new_bay_count",
        "block_reallocation_quantity",
        "stability_cost",
    ):
        expected = canonical[name]
        if name in solution.get("components", {}):
            record(
                f"{name}_accounting",
                abs(solution["components"][name] - expected),
            )
    auxiliary_pairs = {
        "pair_cancellation": "pair_cancellation",
        "pair_discretionary_cancel": "pair_discretionary_cancel",
        "block_reallocation": "pair_block_reallocation",
    }
    stability_pairs = set(_dependency_pairs(d))
    for variable_name, canonical_name in auxiliary_pairs.items():
        actual_values = solution.get(variable_name, {})
        expected_values = canonical[canonical_name]
        for pair in stability_pairs:
            record(
                f"{variable_name}_accounting",
                abs(
                    actual_values.get(pair, 0)
                    - expected_values.get(pair, 0)
                ),
            )

    _record_operation_accounting(
        d,
        solution,
        record,
        operation_weights=operation_weights,
    )

    maximum = max(violations.values(), default=0)
    return {
        "feasible": maximum <= tol,
        "max_violation": maximum,
        "violations": violations,
    }


def solve_rolling_snapshot(
    d: dict,
    *,
    time_limit: float = 60,
    mip_gap: float = .01,
    threads: int = 1,
    seed: int = 0,
    impact_threshold: float = .10,
    configuration: str = "full_bottleneck",
    dependency_profile: str = "current",
    operation_weights: Mapping[str, float] | None = None,
    verbose: bool = False,
) -> dict:
    if dependency_profile not in DEPENDENCY_PROFILES:
        raise ValueError(
            f"dependency_profile must be one of {tuple(DEPENDENCY_PROFILES)}"
        )
    dependency_thresholds = DEPENDENCY_PROFILES[dependency_profile]
    settings = configuration_features(configuration)
    wall_start = time.perf_counter()
    deadline = wall_start + max(0.0, time_limit)
    # Leave a bounded tail for complete incumbent extraction. The reserve is
    # inside the common online-decision budget, not extra method time.
    postprocessing_reserve = postprocessing_reserve_seconds(time_limit)
    optimization_deadline = max(wall_start, deadline - postprocessing_reserve)
    timing = {
        "direct_impact_time": 0.0,
        "pressure_diagnostic_time": 0.0,
        "aggregate_domain_ladder_time": 0.0,
        "objective_scale_time": 0.0,
        "block_score_time": 0.0,
        "dependency_graph_time": 0.0,
        "propagation_time": 0.0,
        "bottleneck_selection_time": 0.0,
        "model_build_time": 0.0,
        "solver_time": 0.0,
        "solution_extract_time": 0.0,
        "model_dispose_time": 0.0,
        "final_model_dispose_time": 0.0,
        "validation_time": 0.0,
    }

    direct_pairs: set[Pair] = set()
    direct_reasons: dict[Pair, list[str]] = {}
    impact_direction: dict[Pair, str] = {}
    if settings["impact_region"] and time.perf_counter() < deadline:
        started = time.perf_counter()
        direct_pairs, direct_reasons = _direct_impact_pairs(d, impact_threshold)
        impact_direction = _impact_directions(d)
        timing["direct_impact_time"] = time.perf_counter() - started

    pressure_diagnostics = {
        "policy": "disabled",
        "route": "configured_stage_path",
        "route_to_global": False,
    }
    if settings["adaptive_global_bypass"] and time.perf_counter() < deadline:
        started = time.perf_counter()
        pressure_diagnostics = _snapshot_pressure_diagnostics(d, direct_pairs)
        timing["pressure_diagnostic_time"] = time.perf_counter() - started
    legacy_pressure_route = bool(pressure_diagnostics["route_to_global"])
    adaptive_global_bypass = bool(
        settings["adaptive_global_bypass"]
        and legacy_pressure_route
        and not settings["aggregate_domain_ladder"]
    )
    impact_preprocessing_enabled = (
        settings["impact_region"]
        and (
            settings["aggregate_domain_ladder"]
            or not adaptive_global_bypass
        )
    )

    objective_scales: dict[str, float] = {}
    if time.perf_counter() < deadline:
        started = time.perf_counter()
        objective_scales = compute_objective_scales(d)
        timing["objective_scale_time"] = time.perf_counter() - started

    scores: dict = {}
    physical_scores: dict = {}
    if (
        impact_preprocessing_enabled
        and settings["dependency_propagation"]
        and time.perf_counter() < deadline
    ):
        started = time.perf_counter()
        physical_scores = _block_scores(d, capacity_basis="physical")
        scores = physical_scores
        timing["block_score_time"] = time.perf_counter() - started

    dependency_graph: dict = {}
    dependency_edges: list[dict] = []
    if (
        impact_preprocessing_enabled
        and settings["dependency_propagation"]
        and time.perf_counter() < deadline
    ):
        started = time.perf_counter()
        dependency_graph, dependency_edges, _resource = _build_dependency_graph(
            d,
            physical_scores,
        )
        timing["dependency_graph_time"] = time.perf_counter() - started

    started = time.perf_counter()
    # Dependency neighbors are intentionally not released in the first solve.
    # They enter only after an incumbent exposes predicted shortage, preserving
    # the robust direct-impact plan in ordinary rolling cycles.
    propagation = _propagate_impact_pairs(
        direct_pairs,
        {},
        impact_direction=impact_direction,
        max_depth=0,
    )
    timing["propagation_time"] = time.perf_counter() - started

    propagated_pairs = set(propagation["propagated_pairs"])
    affected_pairs = set(propagation["affected_pairs"])
    frozen_pairs = set(d["remaining_demand"]) - affected_pairs
    if impact_preprocessing_enabled and time.perf_counter() < deadline:
        started = time.perf_counter()
        physical_residual = physical_residual_capacity_by_bay_period(d)
        baseline_residual = baseline_residual_capacity_by_bay_period(
            d,
            frozen_pairs,
            physical_residual,
        )
        scores = _block_scores(
            d,
            baseline_residual,
            capacity_basis="frozen_plan_baseline",
        )
        timing["block_score_time"] += time.perf_counter() - started
    diagnostic_path_scores = dict(propagation["best_path_score"])
    diagnostic_depths = dict(propagation["propagation_depth"])
    propagation_types = dict(propagation["propagation_type"])
    release_opportunity_blocks: dict[Pair, set[str]] = {}
    for pair in sorted(propagated_pairs):
        if propagation_types.get(pair) != "release_opportunity":
            continue
        ancestor = pair
        while propagation["parent_pair"].get(ancestor) is not None:
            ancestor = propagation["parent_pair"][ancestor]
        release_opportunity_blocks[pair] = existing_blocks(d, ancestor[0], ancestor[1])

    selected_initial_level = 0
    aggregate_ladder_diagnostics = {
        "policy": "disabled",
        "selected_level": None,
        "selected_domain": None,
        "runtime_seconds": 0.0,
        "evaluations": [],
    }
    if (
        settings["aggregate_domain_ladder"]
        and scores
        and time.perf_counter() < optimization_deadline
    ):
        remaining_for_ladder = optimization_deadline - time.perf_counter()
        ladder_budget = min(
            AGGREGATE_DOMAIN_LADDER_MAX_SECONDS,
            max(.01, AGGREGATE_DOMAIN_LADDER_BUDGET_RATIO * time_limit),
            max(.01, remaining_for_ladder - .02),
        )
        started = time.perf_counter()
        (
            selected_initial_level,
            aggregate_ladder_diagnostics,
        ) = _select_aggregate_domain_ladder(
            d,
            direct_pairs,
            propagated_pairs,
            scores,
            uncertainty_radius=(
                AGGREGATE_DOMAIN_LADDER_BUFFER_MULTIPLIER
                * float(d.get("forecast_uncertainty_buffer", 0.0))
            ),
            time_limit=ladder_budget,
            threads=threads,
            release_opportunity_blocks=release_opportunity_blocks,
        )
        timing["aggregate_domain_ladder_time"] = (
            time.perf_counter() - started
        )
        aggregate_ladder_diagnostics["allocated_time"] = ladder_budget
        adaptive_global_bypass = selected_initial_level == 3
        pressure_diagnostics = {
            **pressure_diagnostics,
            "legacy_policy": pressure_diagnostics["policy"],
            "legacy_route_to_global": legacy_pressure_route,
            "legacy_route": pressure_diagnostics["route"],
            "policy": "buffered_aggregate_lp_domain_ladder",
            "route_to_global": adaptive_global_bypass,
            "route": (
                "global_core"
                if adaptive_global_bypass
                else "aggregate_screened_local_repair"
            ),
            "screened_recovery_level": (
                None
                if adaptive_global_bypass
                else selected_initial_level
            ),
            "decision_uses_legacy_thresholds": False,
        }

    stability_info = _stability_reference_diagnostics(d)
    preprocessing_time = sum(
        timing[name]
        for name in (
            "direct_impact_time",
            "pressure_diagnostic_time",
            "aggregate_domain_ladder_time",
            "objective_scale_time",
            "block_score_time",
            "dependency_graph_time",
            "propagation_time",
        )
    )
    preprocessing_timed_out = (
        time.perf_counter() >= optimization_deadline
        or not objective_scales
        or (impact_preprocessing_enabled and not scores)
    )
    incumbent = None
    best_key = None
    cycle_first_incumbent = [None]
    trace: list[dict] = []
    repair_expansions = 0
    quality_triggered = False
    quality_improved = False
    repair_pairs: set[Pair] = set()
    bottleneck_repair_plans: list[dict] = []
    decision_ready_elapsed: float | None = None
    if settings["aggregate_domain_ladder"] and selected_initial_level == 3:
        stages = [(3, "aggregate_ladder_global_core", None)]
    elif settings["aggregate_domain_ladder"]:
        screened_local_allowed = _allowed(
            d,
            0,
            direct_pairs,
            propagated_pairs,
            scores,
            release_opportunity_blocks=release_opportunity_blocks,
        )
        stages = [(
            0,
            "aggregate_screened_impact_region",
            screened_local_allowed,
        )]
    elif adaptive_global_bypass:
        stages = [(3, "adaptive_global_core", None)]
    elif not settings["impact_region"]:
        stages = [(3, "global_core", None)]
    else:
        stages = [(0, "impact_region", None)]
    position = 0

    while position < len(stages) and not preprocessing_timed_out:
        stage_wall_start = time.perf_counter()
        remaining_wall = optimization_deadline - stage_wall_start
        if remaining_wall <= .01:
            break
        level, name, explicit_allowed = stages[position]
        if explicit_allowed is not None:
            allowed = explicit_allowed
        elif level == 3:
            allowed = None
        else:
            allowed = _allowed(
                d,
                level,
                direct_pairs,
                propagated_pairs,
                scores,
                repair_pairs,
                release_opportunity_blocks,
            )
        initial_impact_stage = (
            name == "impact_region"
            or name == "aggregate_screened_impact_region"
        )
        global_repair_time_reserve = 0.0
        if settings["progressive_repair"] and initial_impact_stage:
            requested_stage_time = min(remaining_wall, max(.05, .35 * time_limit))
        elif settings["progressive_repair"] and name == "bottleneck_repair":
            global_repair_time_reserve = global_repair_reserve_seconds(
                time_limit,
                remaining_wall,
            )
            requested_stage_time = max(
                .01,
                remaining_wall - global_repair_time_reserve,
            )
        elif settings["progressive_repair"] and name.startswith("adaptive_repair"):
            requested_stage_time = min(remaining_wall, max(.05, remaining_wall / 2))
        else:
            requested_stage_time = remaining_wall
        stage_deadline = min(
            optimization_deadline,
            stage_wall_start + requested_stage_time,
        )

        build_started = time.perf_counter()
        model, variables, expressions = build_rolling_model(
            d,
            allowed_bays=allowed,
            shortage_allowed=True,
            objective_scales=objective_scales,
            operation_weights=operation_weights,
        )
        build_time = time.perf_counter() - build_started
        timing["model_build_time"] += build_time
        start_stats = _submit_start(
            variables,
            d,
            incumbent,
            enabled=settings["mip_start"],
        )
        solver_budget = stage_deadline - time.perf_counter()
        if solver_budget <= .01:
            timeout_record = {
                "stage": name,
                "neighborhood_level": level,
                "status": "model_build_time_limit",
                "model_build_time": build_time,
                "global_repair_time_reserve": global_repair_time_reserve,
                "solver_runtime": 0.0,
                "solver_time_window": max(0.0, solver_budget),
                "allocated_solver_time": 0.0,
                "solver_return_guard": 0.0,
                "solver_return_overrun": 0.0,
                "solver_budget_binding": False,
                "stage_wall_time": time.perf_counter() - stage_wall_start,
                "variables": int(model.NumVars),
                "binary_variables": int(model.NumBinVars),
                "constraints": int(model.NumConstrs),
                "has_solution": False,
                "solution_count": 0,
                "objective_bound": None,
                "mip_gap": None,
                "root_relaxation": None,
                "stage_first_incumbent_time": None,
                "first_incumbent_time": None,
                "hard_stability_budget_enabled": False,
                "stability_formulation": (
                    "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
                ),
            }
            dispose_started = time.perf_counter()
            model.dispose()
            dispose_time = time.perf_counter() - dispose_started
            timing["model_dispose_time"] += dispose_time
            del model, variables, expressions
            remaining_after_build = optimization_deadline - time.perf_counter()
            global_already_scheduled = any(
                stage_name == "global_repair"
                for _stage_level, stage_name, _stage_allowed
                in stages[position + 1:]
            )
            transition, transition_reason = _restricted_build_timeout_transition(
                progressive_repair=settings["progressive_repair"],
                stage_level=level,
                stage_name=name,
                incumbent_shortage=(
                    (incumbent or {}).get("components", {}).get(
                        "predicted_shortage"
                    )
                ),
                remaining_wall=remaining_after_build,
                global_already_scheduled=global_already_scheduled,
            )
            timeout_record["model_build_timeout_transition"] = transition_reason
            trace.append(timeout_record)
            if transition == "enqueue":
                stages.append((3, "global_repair", None))
                repair_expansions += 1
            if transition in ("enqueue", "continue"):
                position += 1
                continue
            timing["final_model_dispose_time"] += dispose_time
            decision_ready_elapsed = time.perf_counter() - wall_start
            break

        model.Params.OutputFlag = int(verbose)
        model.Params.Threads = threads
        model.Params.Seed = seed
        model.Params.MIPGap = mip_gap
        if level == 3:
            # Large global snapshots previously spent almost the entire
            # online window before producing an incumbent. Favor feasible
            # solutions and give the sparse previous-plan MIP start a bounded
            # repair search; the lexicographic objectives and validation are
            # unchanged.
            model.Params.MIPFocus = GLOBAL_CORE_MIP_FOCUS
            model.Params.Heuristics = GLOBAL_CORE_HEURISTICS
            model.Params.StartNodeLimit = GLOBAL_CORE_START_NODE_LIMIT
        solver_return_guard = solver_return_guard_seconds(
            time_limit,
            solver_budget,
        )
        effective_solver_budget = max(
            .01,
            solver_budget - solver_return_guard,
        )
        solver_stop_deadline = min(
            stage_deadline,
            time.perf_counter() + effective_solver_budget,
        )
        model.Params.TimeLimit = effective_solver_budget
        first = [None]
        optimize_started = time.perf_counter()

        def callback(_model, where):
            if time.perf_counter() >= solver_stop_deadline:
                _model.terminate()
                return
            if where == GRB.Callback.MIPSOL and first[0] is None:
                first[0] = time.perf_counter() - stage_wall_start
            if where == GRB.Callback.MIPSOL and cycle_first_incumbent[0] is None:
                cycle_first_incumbent[0] = time.perf_counter() - wall_start

        diagnostic_pairs = repair_pairs or affected_pairs
        ranking = {}
        for ship, group in sorted(
            diagnostic_pairs & set(d["remaining_demand"])
            if scores
            else ()
        ):
            entries = []
            for block in sorted(
                d["blocks"],
                key=lambda item: (-scores[ship, group, item]["score"], item),
            )[:3]:
                entries.append({
                    "block": block,
                    **{
                        key: value
                        for key, value in scores[ship, group, block].items()
                        if key not in ("capacity_by_period", "arrival_weight")
                    },
                })
            ranking[f"{ship}|{group}"] = entries
        termination_timer = threading.Timer(
            max(.001, solver_stop_deadline - time.perf_counter()),
            model.terminate,
        )
        termination_timer.daemon = True
        termination_timer.start()
        try:
            model.optimize(callback)
        finally:
            termination_timer.cancel()
        solver_returned_at = time.perf_counter()
        solver_runtime = float(model.Runtime)
        solver_limit_status = int(model.Status) in {
            GRB.TIME_LIMIT,
            GRB.INTERRUPTED,
        }
        solver_budget_binding = bool(
            solver_limit_status
            and solver_returned_at >= solver_stop_deadline - .05
        )
        timing["solver_time"] += solver_runtime
        try:
            objective_bound = float(model.ObjBound)
            if not math.isfinite(objective_bound):
                objective_bound = None
        except (AttributeError, ValueError):
            objective_bound = None
        try:
            stage_gap = float(model.MIPGap) if model.SolCount else None
            if stage_gap is not None and not math.isfinite(stage_gap):
                stage_gap = None
        except (AttributeError, ValueError):
            stage_gap = None
        record = {
            "stage": name,
            "neighborhood_level": level,
            "hard_stability_budget_enabled": False,
            "global_repair_time_reserve": global_repair_time_reserve,
            "stability_formulation": (
                "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
            ),
            "solver_time_window": solver_budget,
            "allocated_solver_time": effective_solver_budget,
            "solver_return_guard": solver_return_guard,
            "solver_return_overrun": max(
                0.0,
                solver_returned_at - solver_stop_deadline,
            ),
            "solver_budget_binding": solver_budget_binding,
            "expanded_shortage_pairs": [list(pair) for pair in sorted(repair_pairs)],
            "top_block_scores": ranking,
            "direct_pair_count": len(direct_pairs),
            "propagated_pair_count": len(propagated_pairs),
            "affected_pair_count": len(affected_pairs),
            "allowed_pair_bay_count": (
                sum(len(value) for value in allowed.values())
                if allowed is not None
                else sum(
                    1
                    for bay in d["bays"]
                    for _ship, group in d["remaining_demand"]
                    if compatible(d, bay, group)
                )
            ),
            "dependency_expansion_count": len(propagated_pairs),
            "status": int(model.Status),
            "runtime": solver_runtime,
            "solver_runtime": solver_runtime,
            "model_build_time": build_time,
            "nodes": float(model.NodeCount),
            "variables": int(model.NumVars),
            "binary_variables": int(model.NumBinVars),
            "constraints": int(model.NumConstrs),
            "has_solution": bool(model.SolCount),
            "solution_count": int(model.SolCount),
            "objective_bound": objective_bound,
            "mip_gap": stage_gap,
            "root_relaxation": None,
            "stage_first_incumbent_time": first[0],
            "first_incumbent_time": first[0],
            "mip_start": start_stats,
        }
        previous_key = best_key
        if model.SolCount:
            if cycle_first_incumbent[0] is None:
                cycle_first_incumbent[0] = time.perf_counter() - wall_start
            extract_started = time.perf_counter()
            candidate = extract_rolling_solution(
                variables,
                expressions,
                model=model,
                snapshot=d,
            )
            candidate["components"]["predicted_shortage"] = float(
                sum(candidate["shortage"].values())
            )
            # Absolute-deviation variables are epigraphs.  At a time limit the
            # third-priority operations objective may not have tightened them,
            # so expression values are not reliable physical accounting.  Use
            # extracted flows for incumbent comparison and downstream audit,
            # just as stability is canonicalized below.
            modeled_balance = float(
                candidate["components"]["occupancy_balance_raw"]
            )
            canonical_operations = evaluate_operation_components(
                d,
                candidate["reservation"],
                candidate["din"],
                objective_scales=objective_scales,
                operation_weights=operation_weights,
            )
            record["occupancy_balance_epigraph_slack"] = abs(
                modeled_balance
                - canonical_operations["occupancy_balance_raw"]
            )
            candidate["components"].update(canonical_operations)
            canonical = canonical_stability_metrics(
                d,
                candidate["reservation"],
                candidate["shortage"],
            )
            canonical_auxiliary_mapping = {
                "pair_cancellation": canonical["pair_cancellation"],
                "pair_discretionary_cancel": canonical[
                    "pair_discretionary_cancel"
                ],
                "block_reallocation": canonical["pair_block_reallocation"],
            }
            modeled_epigraph_mapping = {
                "block_reallocation": canonical["pair_block_reallocation"],
            }
            record["stability_epigraph_max_slack"] = max(
                (
                    abs(candidate.get(name, {}).get(pair, 0) - expected.get(pair, 0))
                    for name, expected in modeled_epigraph_mapping.items()
                    for pair in set(candidate.get(name, {})) | set(expected)
                ),
                default=0.0,
            )
            candidate["components"].update(canonical)
            for auxiliary_name, expected in canonical_auxiliary_mapping.items():
                candidate[auxiliary_name] = dict(expected)
            timing["solution_extract_time"] += time.perf_counter() - extract_started
            components = candidate["components"]
            key = _incumbent_key(components)
            record.update({
                field: components[field]
                for field in (
                    "predicted_shortage",
                    "cancellation_quantity",
                    "mandatory_reduction",
                    "discretionary_cancel",
                    "new_bay_count",
                    "block_reallocation_quantity",
                    "stability_cost",
                    "normalized_operations_score",
                    "concentration_raw",
                    "concentration_normalized",
                    "distance_raw",
                    "distance_normalized",
                    "in_out_conflict_raw",
                    "in_out_conflict_normalized",
                    "occupancy_balance_raw",
                    "occupancy_balance_normalized",
                )
            })
            accepted, acceptance_reason = _incumbent_decision(key, best_key)
            record["candidate_quality_key"] = list(key)
            record["incumbent_quality_key_before"] = (
                list(best_key) if best_key is not None else None
            )
            record["candidate_accepted"] = accepted
            record["incumbent_acceptance_reason"] = acceptance_reason
            if accepted:
                incumbent, best_key = candidate, key
            record["incumbent_quality_key_after"] = (
                list(best_key) if best_key is not None else None
            )
            if name == "quality_polish":
                quality_improved = previous_key is None or best_key < previous_key
        record["stage_wall_time"] = time.perf_counter() - stage_wall_start
        trace.append(record)
        position += 1
        record["progressive_repair_enabled"] = settings["progressive_repair"]
        shortage_pairs = {
            (ship, group)
            for (ship, group, _period), quantity
            in (incumbent or {}).get("shortage", {}).items()
            if quantity > 1e-6
        }
        shortage_free = bool(
            incumbent
            and incumbent["components"]["predicted_shortage"] <= 1e-6
        )
        requires_postsolve_planning = bool(
            settings["progressive_repair"]
            and (
                not shortage_free
                or (
                    settings["quality_polish"]
                    and name != "quality_polish"
                )
            )
        )
        if not requires_postsolve_planning:
            decision_ready_elapsed = time.perf_counter() - wall_start
            dispose_started = time.perf_counter()
            model.dispose()
            dispose_time = time.perf_counter() - dispose_started
            timing["model_dispose_time"] += dispose_time
            timing["final_model_dispose_time"] += dispose_time
            record["model_dispose_time"] = dispose_time
            del model, variables, expressions
            break

        dispose_started = time.perf_counter()
        model.dispose()
        dispose_time = time.perf_counter() - dispose_started
        timing["model_dispose_time"] += dispose_time
        record["model_dispose_time"] = dispose_time
        del model, variables, expressions
        if settings["progressive_repair"]:
            remaining_wall = optimization_deadline - time.perf_counter()
            record["postsolve_predicted_shortage"] = (
                incumbent["components"]["predicted_shortage"]
                if incumbent
                else None
            )
            record["postsolve_shortage_pair_count"] = len(shortage_pairs)
            record["postsolve_remaining_wall_time"] = remaining_wall
            if shortage_free:
                if (
                    settings["quality_polish"]
                    and name != "quality_polish"
                    and remaining_wall > .05
                ):
                    polish_allowed, info = _quality_polish_allowed(
                        d,
                        affected_pairs,
                        direct_pairs,
                        propagated_pairs,
                        scores,
                        incumbent,
                        release_opportunity_blocks,
                    )
                    quality_triggered = True
                    stages.append((0, "quality_polish", polish_allowed))
                    record["quality_polish_plan"] = info
            else:
                if shortage_pairs:
                    for pair in shortage_pairs:
                        direct_pairs.add(pair)
                        direct_reasons.setdefault(
                            pair,
                            [],
                        ).append("shortage_repair")
                        impact_direction[pair] = "increase"
                        diagnostic_path_scores[pair] = max(
                            1.0,
                            diagnostic_path_scores.get(pair, 0.0),
                        )
                        diagnostic_depths[pair] = 0
                        propagation_types[pair] = "pressure"
                    propagated_pairs -= shortage_pairs
                    repair_pairs |= shortage_pairs
                    affected_pairs |= shortage_pairs
                    if settings["dependency_propagation"]:
                        repair_prop = _propagate_impact_pairs(
                            shortage_pairs,
                            dependency_graph,
                            impact_direction=impact_direction,
                            max_depth=1,
                            edge_threshold=dependency_thresholds[
                                "edge_threshold"
                            ],
                            path_threshold=dependency_thresholds[
                                "path_threshold"
                            ],
                        )
                        new_neighbors = (
                            set(repair_prop["propagated_pairs"])
                            - direct_pairs
                        )
                        propagated_pairs |= new_neighbors
                        affected_pairs |= new_neighbors
                        repair_pairs |= new_neighbors
                        for pair in sorted(new_neighbors):
                            score = repair_prop["best_path_score"][pair]
                            if score > diagnostic_path_scores.get(pair, -1):
                                diagnostic_path_scores[pair] = score
                                diagnostic_depths[pair] = repair_prop[
                                    "propagation_depth"
                                ][pair]
                                propagation_types[pair] = repair_prop[
                                    "propagation_type"
                                ][pair]
                if settings["bottleneck_repair"]:
                    if initial_impact_stage:
                        selector_budget = min(
                            BOTTLENECK_SELECTOR_MAX_SECONDS,
                            max(
                                .01,
                                BOTTLENECK_SELECTOR_BUDGET_RATIO
                                * time_limit,
                            ),
                            max(.01, remaining_wall - .01),
                        )
                        selection_started = time.perf_counter()
                        if (
                            incumbent
                            and shortage_pairs
                            and remaining_wall > .02
                        ):
                            (
                                repair_allowed,
                                plan,
                            ) = _bottleneck_minimal_expansion(
                                d,
                                allowed,
                                incumbent,
                                shortage_pairs,
                                scores,
                                time_limit=selector_budget,
                                seed=seed,
                            )
                        else:
                            repair_allowed = allowed
                            plan = {
                                "selector": (
                                    "granularity_guarded_minimum_pair_block_cover"
                                ),
                                "status": "no_usable_incumbent_or_time",
                                "shortage_pairs": [
                                    list(pair)
                                    for pair in sorted(shortage_pairs)
                                ],
                                "selected_pair_blocks": {},
                                "selected_pair_block_count": 0,
                                "selector_runtime": 0.0,
                            }
                        timing["bottleneck_selection_time"] += (
                            time.perf_counter() - selection_started
                        )
                        plan["allocated_selector_time"] = selector_budget
                        bottleneck_repair_plans.append(plan)
                        record["bottleneck_repair_plan"] = plan
                        if plan["selected_pair_block_count"] > 0:
                            stages.append(
                                (1, "bottleneck_repair", repair_allowed)
                            )
                        else:
                            stages.append((3, "global_repair", None))
                        repair_expansions += 1
                    elif name == "bottleneck_repair":
                        global_already_scheduled = any(
                            stage_name == "global_repair"
                            for _stage_level, stage_name, _stage_allowed
                            in stages[position:]
                        )
                        enqueue_global, global_decision = (
                            _post_bottleneck_global_repair_decision(
                                stage_name=name,
                                predicted_shortage=(
                                    (incumbent or {}).get("components", {}).get(
                                        "predicted_shortage"
                                    )
                                ),
                                remaining_wall=remaining_wall,
                                already_scheduled=global_already_scheduled,
                            )
                        )
                        record["global_repair_decision"] = global_decision
                        if enqueue_global:
                            stages.append((3, "global_repair", None))
                            repair_expansions += 1
                elif name == "impact_region":
                    stages.append((1, "adaptive_repair_1", None))
                    repair_expansions += 1
                elif name == "adaptive_repair_1":
                    stages.append((2, "adaptive_repair_2", None))
                    repair_expansions += 1
                elif name == "adaptive_repair_2":
                    stages.append((3, "global_repair", None))
                    repair_expansions += 1

        more_online_work = (
            position < len(stages)
            and time.perf_counter() < optimization_deadline
        )
        if not more_online_work:
            decision_ready_elapsed = time.perf_counter() - wall_start
        if not more_online_work:
            break

    if decision_ready_elapsed is None:
        decision_ready_elapsed = time.perf_counter() - wall_start
    optimization_budget_binding = (
        decision_ready_elapsed
        >= max(0.0, time_limit - postprocessing_reserve) - .01
        or any(
            bool(record.get("solver_budget_binding"))
            for record in trace
        )
    )
    validation_started = time.perf_counter()
    report = (
        validate_rolling_solution(
            d,
            incumbent,
            operation_weights=operation_weights,
        )
        if incumbent else None
    )
    timing["validation_time"] = time.perf_counter() - validation_started
    audit_wall_time = time.perf_counter() - wall_start
    deadline_exceeded = (
        decision_ready_elapsed
        > time_limit + WALL_TIME_TOLERANCE_SECONDS
    )
    path_scores = {
        f"{ship}|{group}": score
        for (ship, group), score in sorted(diagnostic_path_scores.items())
    }
    impact_diagnostics = {
        "dependency_profile": dependency_profile,
        "dependency_trigger_mode": DEPENDENCY_TRIGGER_MODE,
        "dependency_edge_threshold": dependency_thresholds["edge_threshold"],
        "dependency_path_threshold": dependency_thresholds["path_threshold"],
        "direct_pairs": [list(pair) for pair in sorted(direct_pairs)],
        "direct_reasons": {
            f"{ship}|{group}": reasons
            for (ship, group), reasons in sorted(direct_reasons.items())
        },
        "impact_direction": {
            f"{ship}|{group}": direction
            for (ship, group), direction in sorted(impact_direction.items())
        },
        "propagated_pairs": [list(pair) for pair in sorted(propagated_pairs)],
        "pressure_propagation": [
            list(pair)
            for pair in sorted(propagated_pairs)
            if propagation_types.get(pair) == "pressure"
        ],
        "release_opportunity_propagation": [
            list(pair)
            for pair in sorted(propagated_pairs)
            if propagation_types.get(pair) == "release_opportunity"
        ],
        "affected_pairs": [list(pair) for pair in sorted(affected_pairs)],
        "frozen_pairs": [list(pair) for pair in sorted(frozen_pairs)],
        "dependency_capacity_basis": "physical_residual_capacity",
        "candidate_ranking_capacity_basis": "frozen_plan_baseline_residual_capacity",
        "propagation_enabled": settings["dependency_propagation"],
        "max_depth_reached": max(diagnostic_depths.values(), default=0),
        "dependency_edge_count": len(dependency_edges),
        "top_dependency_edges": dependency_edges[:20],
        "path_scores": path_scores,
        "release_opportunity_blocks": {
            f"{ship}|{group}": sorted(blocks)
            for (ship, group), blocks in sorted(release_opportunity_blocks.items())
            if blocks
        },
        "bottleneck_repair_enabled": settings["bottleneck_repair"],
        "bottleneck_repair_plans": bottleneck_repair_plans,
        "adaptive_global_bypass_enabled": settings["adaptive_global_bypass"],
        "adaptive_pressure": pressure_diagnostics,
        "aggregate_domain_ladder_enabled": settings["aggregate_domain_ladder"],
        "aggregate_domain_ladder": aggregate_ladder_diagnostics,
    }
    solution_valid = bool(
        incumbent
        and report
        and report["feasible"]
    )
    failure_status = None
    if incumbent is None:
        failure_status = (
            "preprocessing_time_limit"
            if preprocessing_timed_out
            else "no_incumbent"
        )
    elif report and not report["feasible"]:
        failure_status = "solution_validation_failed"
    elif deadline_exceeded:
        failure_status = "online_decision_time_limit_exceeded"
    if not solution_valid:
        termination_status = (
            "VALIDATION_FAILED"
            if incumbent is not None and report is not None
            else "DEADLINE_MISS"
        )
    elif deadline_exceeded:
        termination_status = "DEADLINE_MISS"
    elif optimization_budget_binding:
        termination_status = "TIME_LIMIT_FEASIBLE"
    else:
        termination_status = "FEASIBLE"
    final_trace = trace[-1] if trace else {}
    final_components = (incumbent or {}).get("components", {})
    return {
        "ok": bool(solution_valid and not deadline_exceeded),
        "failure_status": failure_status,
        "termination_status": termination_status,
        "decision_deadline_met": not deadline_exceeded,
        "optimization_budget_binding": optimization_budget_binding,
        "configuration": configuration,
        "solution": incumbent,
        "validation": report,
        "affected_ships": sorted({ship for ship, _group in affected_pairs}),
        "impact_diagnostics": impact_diagnostics,
        "stability_diagnostics": stability_info,
        "objective_scales": objective_scales,
        "stages": trace,
        "repair_triggered": settings["progressive_repair"] and repair_expansions > 0,
        "repair_expansions": repair_expansions,
        "adaptive_global_bypass": adaptive_global_bypass,
        "adaptive_pressure": pressure_diagnostics,
        "aggregate_domain_ladder": aggregate_ladder_diagnostics,
        "bottleneck_repair_triggered": bool(bottleneck_repair_plans),
        "bottleneck_selected_pair_block_count": sum(
            plan.get("selected_pair_block_count", 0)
            for plan in bottleneck_repair_plans
        ),
        "quality_polish_triggered": quality_triggered,
        "quality_polish_improved": quality_improved,
        "preprocessing_time": preprocessing_time,
        **timing,
        "online_decision_time": decision_ready_elapsed,
        "audit_wall_time": audit_wall_time,
        "total_wall_time": audit_wall_time,
        "runtime": decision_ready_elapsed,
        "wall_time_limit": time_limit,
        "wall_time_tolerance": WALL_TIME_TOLERANCE_SECONDS,
        "postprocessing_time_reserve": postprocessing_reserve,
        "final_stage": trace[-1]["stage"] if trace else None,
        "cycle_first_incumbent_wall_time": cycle_first_incumbent[0],
        "final_predicted_shortage": final_components.get("predicted_shortage"),
        "final_stability_cost": final_components.get("stability_cost"),
        "final_normalized_operations_score": final_components.get(
            "normalized_operations_score"
        ),
        "final_stage_objective_bound": final_trace.get("objective_bound"),
        "final_stage_mip_gap": final_trace.get("mip_gap"),
        "stability_formulation": (
            "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
        ),
    }

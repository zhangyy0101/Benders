"""Dependency-aware impact regions, progressive repair, and validation."""
from __future__ import annotations

import math
import time
from collections import deque
from typing import TypeAlias

from gurobipy import GRB

from config import (
    ADAPTIVE_BLOCK_BATCH_RATIO,
    DEPENDENCY_CANDIDATE_BLOCK_RATIO,
    DEPENDENCY_DECAY,
    DEPENDENCY_EDGE_THRESHOLD,
    DEPENDENCY_MAX_DEPTH,
    DEPENDENCY_MAX_NEIGHBORS_PER_PAIR,
    DEPENDENCY_PATH_THRESHOLD,
    DEPENDENCY_PROPAGATION_ENABLED,
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
    QUALITY_POLISH_BLOCKS_PER_PAIR,
    QUALITY_POLISH_ENABLED,
    QUALITY_POLISH_PAIR_RATIO,
    QUALITY_POLISH_WEIGHT_DISTANCE,
    QUALITY_POLISH_WEIGHT_OVERLAP,
    QUALITY_POLISH_WEIGHT_SUPPORT,
    QUALITY_POLISH_WEIGHT_UTILIZATION,
    POSTPROCESSING_RESERVE_MAX_SECONDS,
    POSTPROCESSING_RESERVE_MIN_SECONDS,
    POSTPROCESSING_RESERVE_RATIO,
    STABILITY_BASE_RATIO,
    STABILITY_BLOCK_REALLOCATION_WEIGHT,
    STABILITY_CANCEL_WEIGHT,
    STABILITY_CHANGE_RATIO,
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
    existing_blocks,
    existing_support,
    extract_rolling_solution,
    ship_present_at,
)

Pair: TypeAlias = tuple[str, str]
INF = 10**9
CONFIGURATIONS = ("core", "core_start", "core_start_impact", "full_direct", "full")


def postprocessing_reserve_seconds(time_limit: float) -> float:
    """Reserve a common bounded wall-clock tail for extraction and validation."""
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


def configuration_features(configuration: str) -> dict:
    """Expose ablation switches so tests and experiment metadata stay aligned."""
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"configuration must be one of {CONFIGURATIONS}")
    return {
        "mip_start": configuration != "core",
        "impact_region": configuration not in ("core", "core_start"),
        "dependency_propagation": configuration == "full" and DEPENDENCY_PROPAGATION_ENABLED,
        "progressive_repair": configuration in ("full_direct", "full"),
        "quality_polish": (
            QUALITY_POLISH_ENABLED
            and configuration in ("full_direct", "full")
        ),
    }


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


def _dynamic_stability_budget(d: dict) -> dict:
    old = _pair_totals(d["previous_reservation"])
    current = d["remaining_demand"]
    keys = set(old) | set(current)
    prediction_change = sum(abs(current.get(key, 0) - old.get(key, 0)) for key in keys)
    mandatory = sum(max(0, old.get(key, 0) - current.get(key, 0)) for key in keys)
    allowance = math.ceil(
        STABILITY_BASE_RATIO * sum(old.values()) + STABILITY_CHANGE_RATIO * prediction_change
    )
    return {
        "allowance": allowance,
        "mandatory_reduction": mandatory,
        "prediction_change": prediction_change,
        "previous_reservation": sum(old.values()),
        "pair_allowance_basis": {
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
    residual: dict[tuple[str, int], float] = {}
    for bay in d["bays"]:
        for period in d["periods"]:
            locked = sum(
                quantity
                for (i, old_ship), quantity in d["locked_inventory"].items()
                if i == bay
                and d["locked_release_local"].get((i, old_ship), INF) > period
            )
            actual = sum(
                quantity
                for (i, ship, _group), quantity in d["actual_inventory"].items()
                if i == bay and ship_present_at(d, ship, period)
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
    result: dict[tuple[str, int], float] = {}
    for bay in d["bays"]:
        for period in d["periods"]:
            committed = 0.0
            for ship, group in frozen_pairs:
                if not ship_present_at(d, ship, period):
                    continue
                scheduled = sum(
                    quantity
                    for (i, j, g, arrival), quantity in previous_din.items()
                    if i == bay
                    and j == ship
                    and g == group
                    and arrival <= period
                )
                has_schedule = any(
                    i == bay and j == ship and g == group
                    for i, j, g, _arrival in previous_din
                )
                committed += (
                    scheduled
                    if has_schedule
                    else d["previous_reservation"].get((bay, ship, group), 0)
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
            compatible_bays = [
                bay for bay in d["bays_in_block"][block] if compatible(d, bay, group)
            ]
            for period in periods:
                capacity = 0.0
                conflicts = 0
                for bay in compatible_bays:
                    fixed_heights = _base_heights(d, bay, period)
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


def _submit_start(variables: dict, d: dict, incumbent: dict | None = None, enabled: bool = True) -> dict:
    if not enabled:
        return {"submitted": False, "source": "disabled", "nonzero_values": 0, "covered_variables": 0}
    source = (incumbent or {}).get("reservation", d["previous_reservation"])
    flows = (incumbent or {}).get("din", d.get("previous_din", {}))
    nonzero = covered = 0
    for key, variable in variables["reservation"].items():
        value = float(source.get(key, 0));variable.Start = value
        covered += int(key in source);nonzero += int(abs(value) > 1e-9)
    for key, variable in variables["din"].items():
        value = float(flows.get(key, 0));variable.Start = value
        covered += int(key in flows);nonzero += int(abs(value) > 1e-9)
    structural = 0
    if incumbent:
        for name, group in variables.items():
            if name in ("reservation", "din"):
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
    }


def canonical_stability_metrics(d: dict, reservation: dict, shortage: dict) -> dict:
    """Compute pair-level plan revisions without cross-pair shortage offsets."""
    old = d["previous_reservation"]
    old_totals, current_totals = _pair_totals(old), d["remaining_demand"]
    pairs = set(old_totals) | set(current_totals)
    pair_cancellation: dict[Pair, float] = {}
    pair_discretionary: dict[Pair, float] = {}
    pair_reallocation: dict[Pair, float] = {}
    mandatory_by_pair: dict[Pair, float] = {}
    for j, g in pairs:
        pair = (j, g)
        cancellation = sum(
            max(0, quantity - reservation.get((bay, j, g), 0))
            for (bay, ship, group), quantity in old.items()
            if ship == j and group == g
        )
        mandatory = max(0, old_totals.get(pair, 0) - current_totals.get(pair, 0))
        pair_shortage = sum(
            quantity
            for (ship, group, _period), quantity in shortage.items()
            if ship == j and group == g
        )
        block_cancel = 0.0
        for k in d["blocks"]:
            old_block = _old_block_amount_for_plan(d, old, j, g, k)
            current_block = _old_block_amount_for_plan(d, reservation, j, g, k)
            block_cancel += max(0, old_block - current_block)
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


def _old_block_amount_for_plan(d: dict, plan: dict, j: str, g: str, k: str) -> float:
    return sum(
        q for (i, jj, gg), q in plan.items()
        if jj == j and gg == g and d["bay_block"][i] == k
    )


def validate_rolling_solution(d: dict, solution: dict, tol: float = 1e-6) -> dict:
    reserve, din, inv = solution["reservation"], solution["din"], solution["inventory"]
    shortage, attrs, violations = solution["shortage"], d["group_attrs"], {}
    def record(name: str, value: float) -> None:
        violations[name] = max(violations.get(name, 0), max(0, float(value)))
    for (j, g, n), forecast in d["forecast_arrivals"].items():
        placed = sum(q for (_i, jj, gg, nn), q in din.items() if jj == j and gg == g and nn == n)
        record("period_arrival", abs(placed + shortage.get((j, g, n), 0) - forecast))
    for j, g in d["remaining_demand"]:
        reserved = sum(q for (_i, jj, gg), q in reserve.items() if jj == j and gg == g)
        flowed = sum(q for (_i, jj, gg, _n), q in din.items() if jj == j and gg == g)
        record("reserve_flow", abs(reserved - flowed))
    last = d["periods"][-1]
    for i in d["bays"]:
        locked_final = sum(q for (ii, old), q in d["locked_inventory"].items() if ii == i and d["locked_release_local"].get((ii, old), INF) > last)
        actual_final = sum(q for (ii, j, _g), q in d["actual_inventory"].items() if ii == i and ship_present_at(d, j, last))
        planned_final = sum(q for (ii, j, _g), q in reserve.items() if ii == i and ship_present_at(d, j, last))
        record("final_capacity", locked_final + actual_final + planned_final - d["capacity"][i])
        for n in d["periods"]:
            locked = sum(q for (ii, old), q in d["locked_inventory"].items() if ii == i and d["locked_release_local"].get((ii, old), INF) > n)
            actual = sum(q for (ii, j, _g), q in d["actual_inventory"].items() if ii == i and ship_present_at(d, j, n))
            planned = sum(q for (ii, j, _g, t), q in din.items() if ii == i and t <= n and ship_present_at(d, j, n))
            record("period_capacity", locked + actual + planned - d["capacity"][i])
            used_heights = {h for (ii, old), h in d["locked_height"].items() if ii == i and d["locked_release_local"].get((ii, old), INF) > n}
            used_heights |= {attrs[g]["height"] for (ii, j, g), q in d["actual_inventory"].items() if ii == i and q > tol and ship_present_at(d, j, n)}
            used_heights |= {attrs[g]["height"] for (ii, j, g, t), q in din.items() if ii == i and t <= n and q > tol and ship_present_at(d, j, n)}
            record("height", len(used_heights) - 1)
    for (i, _j, g), q in reserve.items():
        if q > tol:
            record("size", int(d["bay_size"][i] != attrs[g]["size"]))
        record("integrality", abs(q - round(q)))
    for (i, j, g, n), value in inv.items():
        cumulative = sum(q for (ii, jj, gg, t), q in din.items() if ii == i and jj == j and gg == g and t <= n)
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
    maximum = max(violations.values(), default=0)
    return {"feasible": maximum <= tol, "max_violation": maximum, "violations": violations}


def solve_rolling_snapshot(
    d: dict,
    *,
    time_limit: float = 60,
    mip_gap: float = .01,
    threads: int = 1,
    seed: int = 0,
    impact_threshold: float = .10,
    configuration: str = "full",
    verbose: bool = False,
) -> dict:
    settings = configuration_features(configuration)
    wall_start = time.perf_counter()
    deadline = wall_start + max(0.0, time_limit)
    # Leave a bounded tail for incumbent extraction and the mandatory independent
    # validation.  The reserve is part of the common wall-clock budget, not extra
    # time granted to any configuration.
    postprocessing_reserve = postprocessing_reserve_seconds(time_limit)
    optimization_deadline = max(wall_start, deadline - postprocessing_reserve)
    timing = {
        "direct_impact_time": 0.0,
        "objective_scale_time": 0.0,
        "block_score_time": 0.0,
        "dependency_graph_time": 0.0,
        "propagation_time": 0.0,
        "model_build_time": 0.0,
        "solver_time": 0.0,
        "solution_extract_time": 0.0,
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

    objective_scales: dict[str, float] = {}
    if time.perf_counter() < deadline:
        started = time.perf_counter()
        objective_scales = compute_objective_scales(d)
        timing["objective_scale_time"] = time.perf_counter() - started

    scores: dict = {}
    physical_scores: dict = {}
    if settings["impact_region"] and time.perf_counter() < deadline:
        started = time.perf_counter()
        physical_scores = _block_scores(d, capacity_basis="physical")
        scores = physical_scores
        timing["block_score_time"] = time.perf_counter() - started

    dependency_graph: dict = {}
    dependency_edges: list[dict] = []
    if settings["dependency_propagation"] and time.perf_counter() < deadline:
        started = time.perf_counter()
        dependency_graph, dependency_edges, _resource = _build_dependency_graph(
            d,
            physical_scores,
        )
        timing["dependency_graph_time"] = time.perf_counter() - started

    started = time.perf_counter()
    if settings["dependency_propagation"] and time.perf_counter() < deadline:
        propagation = _propagate_impact_pairs(
            direct_pairs,
            dependency_graph,
            impact_direction=impact_direction,
        )
    else:
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
    if settings["impact_region"] and time.perf_counter() < deadline:
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

    budget_info = _dynamic_stability_budget(d)
    preprocessing_time = sum(
        timing[name]
        for name in (
            "direct_impact_time",
            "objective_scale_time",
            "block_score_time",
            "dependency_graph_time",
            "propagation_time",
        )
    )
    preprocessing_timed_out = (
        time.perf_counter() >= optimization_deadline
        or not objective_scales
        or (settings["impact_region"] and not scores)
    )
    incumbent = None
    best_key = None
    cycle_first_incumbent = [None]
    trace: list[dict] = []
    repair_expansions = 0
    quality_triggered = False
    quality_improved = False
    repair_pairs: set[Pair] = set()
    stages = (
        [(3, "global_core", None)]
        if not settings["impact_region"]
        else [(0, "impact_region", None)]
    )
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
        budget = None
        if settings["impact_region"] and level < 3 and name != "quality_polish":
            budget = math.ceil(
                budget_info["allowance"] * (1, 1.5, 2.5)[min(level, 2)]
            )
        if settings["progressive_repair"] and name == "impact_region":
            requested_stage_time = min(remaining_wall, max(.05, .35 * time_limit))
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
            stability_budget=budget,
            objective_scales=objective_scales,
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
            trace.append({
                "stage": name,
                "neighborhood_level": level,
                "status": "model_build_time_limit",
                "model_build_time": build_time,
                "solver_runtime": 0.0,
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
                "stability_budget": budget,
                "stability_budget_disabled": budget is None,
                "stability_formulation": (
                    "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
                ),
            })
            model.dispose()
            del model, variables, expressions
            break

        model.Params.OutputFlag = int(verbose)
        model.Params.Threads = threads
        model.Params.Seed = seed
        model.Params.MIPGap = mip_gap
        model.Params.TimeLimit = max(.01, solver_budget)
        first = [None]
        optimize_started = time.perf_counter()

        def callback(_model, where):
            if where == GRB.Callback.MIPSOL and first[0] is None:
                first[0] = time.perf_counter() - stage_wall_start
            if where == GRB.Callback.MIPSOL and cycle_first_incumbent[0] is None:
                cycle_first_incumbent[0] = time.perf_counter() - wall_start

        diagnostic_pairs = repair_pairs or affected_pairs
        ranking = {}
        for ship, group in sorted(diagnostic_pairs & set(d["remaining_demand"])):
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
        model.optimize(callback)
        solver_runtime = float(model.Runtime)
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
            "stability_budget": budget,
            "stability_budget_disabled": budget is None,
            "stability_formulation": (
                "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
            ),
            "allocated_solver_time": solver_budget,
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
            candidate = extract_rolling_solution(variables, expressions)
            candidate["components"]["predicted_shortage"] = float(
                sum(candidate["shortage"].values())
            )
            canonical = canonical_stability_metrics(
                d,
                candidate["reservation"],
                candidate["shortage"],
            )
            auxiliary_mapping = {
                "pair_cancellation": canonical["pair_cancellation"],
                "pair_discretionary_cancel": canonical[
                    "pair_discretionary_cancel"
                ],
                "block_reallocation": canonical["pair_block_reallocation"],
            }
            record["stability_epigraph_max_slack"] = max(
                (
                    abs(candidate[name].get(pair, 0) - expected.get(pair, 0))
                    for name, expected in auxiliary_mapping.items()
                    for pair in set(candidate[name]) | set(expected)
                ),
                default=0.0,
            )
            candidate["components"].update(canonical)
            if not USE_EXACT_STABILITY_BIG_M:
                for name, expected in auxiliary_mapping.items():
                    candidate[name] = dict(expected)
            timing["solution_extract_time"] += time.perf_counter() - extract_started
            components = candidate["components"]
            key = (
                round(components["predicted_shortage"], 6),
                round(components["stability_cost"], 6),
                round(components["operations_cost"], 9),
            )
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
                    "operations_cost",
                    "in_out_conflict_raw",
                    "occupancy_balance_raw",
                )
            })
            record["stability_budget_binding"] = (
                budget is not None
                and components["discretionary_cancel"] >= budget - 1e-6
            )
            if best_key is None or key < best_key:
                incumbent, best_key = candidate, key
            if name == "quality_polish":
                quality_improved = previous_key is None or best_key < previous_key
        record["stage_wall_time"] = time.perf_counter() - stage_wall_start
        trace.append(record)
        model.dispose()
        del model, variables, expressions
        position += 1
        if not settings["progressive_repair"]:
            continue

        shortage_pairs = {
            (ship, group)
            for (ship, group, _period), quantity in (incumbent or {}).get("shortage", {}).items()
            if quantity > 1e-6
        }
        remaining_wall = optimization_deadline - time.perf_counter()
        if incumbent and incumbent["components"]["predicted_shortage"] <= 1e-6:
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
            continue
        if shortage_pairs:
            for pair in shortage_pairs:
                direct_pairs.add(pair)
                direct_reasons.setdefault(pair, []).append("shortage_repair")
                impact_direction[pair] = "increase"
                diagnostic_path_scores[pair] = max(
                    1.0, diagnostic_path_scores.get(pair, 0.0)
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
                )
                new_neighbors = set(repair_prop["propagated_pairs"]) - direct_pairs
                propagated_pairs |= new_neighbors
                affected_pairs |= new_neighbors
                repair_pairs |= new_neighbors
                for pair in sorted(new_neighbors):
                    score = repair_prop["best_path_score"][pair]
                    if score > diagnostic_path_scores.get(pair, -1):
                        diagnostic_path_scores[pair] = score
                        diagnostic_depths[pair] = repair_prop["propagation_depth"][pair]
                        propagation_types[pair] = repair_prop["propagation_type"][pair]
        if name == "impact_region":
            stages.append((1, "adaptive_repair_1", None))
            repair_expansions += 1
        elif name == "adaptive_repair_1":
            stages.append((2, "adaptive_repair_2", None))
            repair_expansions += 1
        elif name == "adaptive_repair_2":
            stages.append((3, "global_repair", None))
            repair_expansions += 1

    validation_started = time.perf_counter()
    report = validate_rolling_solution(d, incumbent) if incumbent else None
    timing["validation_time"] = time.perf_counter() - validation_started
    total_wall_time = time.perf_counter() - wall_start
    deadline_exceeded = total_wall_time > time_limit + WALL_TIME_TOLERANCE_SECONDS
    path_scores = {
        f"{ship}|{group}": score
        for (ship, group), score in sorted(diagnostic_path_scores.items())
    }
    impact_diagnostics = {
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
    }
    failure_status = None
    if preprocessing_timed_out:
        failure_status = "preprocessing_time_limit"
    elif deadline_exceeded:
        failure_status = "wall_clock_time_limit_exceeded"
    elif incumbent is None:
        failure_status = "no_incumbent"
    elif report and not report["feasible"]:
        failure_status = "solution_validation_failed"
    final_trace = trace[-1] if trace else {}
    final_components = (incumbent or {}).get("components", {})
    return {
        "ok": bool(
            incumbent
            and report
            and report["feasible"]
            and not deadline_exceeded
        ),
        "failure_status": failure_status,
        "configuration": configuration,
        "solution": incumbent,
        "validation": report,
        "affected_ships": sorted({ship for ship, _group in affected_pairs}),
        "impact_diagnostics": impact_diagnostics,
        "stability_budget_diagnostics": budget_info,
        "objective_scales": objective_scales,
        "stages": trace,
        "repair_triggered": settings["progressive_repair"] and repair_expansions > 0,
        "repair_expansions": repair_expansions,
        "quality_polish_triggered": quality_triggered,
        "quality_polish_improved": quality_improved,
        "preprocessing_time": preprocessing_time,
        **timing,
        "total_wall_time": total_wall_time,
        "runtime": total_wall_time,
        "wall_time_limit": time_limit,
        "wall_time_tolerance": WALL_TIME_TOLERANCE_SECONDS,
        "postprocessing_time_reserve": postprocessing_reserve,
        "final_stage": trace[-1]["stage"] if trace else None,
        "cycle_first_incumbent_wall_time": cycle_first_incumbent[0],
        "final_predicted_shortage": final_components.get("predicted_shortage"),
        "final_stability_cost": final_components.get("stability_cost"),
        "final_operations_cost": final_components.get("operations_cost"),
        "final_stage_objective_bound": final_trace.get("objective_bound"),
        "final_stage_mip_gap": final_trace.get("mip_gap"),
        "stability_formulation": (
            "exact_big_m" if USE_EXACT_STABILITY_BIG_M else "epigraph_only"
        ),
    }

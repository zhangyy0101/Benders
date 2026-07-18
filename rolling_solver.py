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
    QUALITY_POLISH_PAIR_RATIO,
    STABILITY_BASE_RATIO,
    STABILITY_BLOCK_REALLOCATION_WEIGHT,
    STABILITY_CANCEL_WEIGHT,
    STABILITY_CHANGE_RATIO,
    STABILITY_NEW_BAY_WEIGHT,
)
from rolling_model import build_rolling_model, compatible, extract_rolling_solution, ship_present_at

Pair: TypeAlias = tuple[str, str]
INF = 10**9
CONFIGURATIONS = ("core", "core_start", "core_start_impact", "full_direct", "full")


def configuration_features(configuration: str) -> dict:
    """Expose ablation switches so tests and experiment metadata stay aligned."""
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"configuration must be one of {CONFIGURATIONS}")
    return {
        "mip_start": configuration != "core",
        "impact_region": configuration not in ("core", "core_start"),
        "dependency_propagation": configuration == "full" and DEPENDENCY_PROPAGATION_ENABLED,
        "progressive_repair": configuration in ("full_direct", "full"),
        "quality_polish": configuration in ("full_direct", "full"),
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
    }


def _block_scores(d: dict) -> dict:
    """Rank blocks with normalized, objective-aligned marginal features."""
    scores = {}
    periods, attrs = d["periods"], d["group_attrs"]
    last = periods[-1]
    max_dist = max(d["distance"].values(), default=1)
    max_out = max(d["forecast_outbound"].values(), default=1)
    old_blocks = {
        (j, g): {
            d["bay_block"][i]
            for (i, jj, gg), q in d["previous_reservation"].items()
            if jj == j and gg == g and q > 0
        }
        for j, g in d["remaining_demand"]
    }
    base_load = {}
    for k in d["blocks"]:
        for n in periods:
            locked = sum(
                q
                for (i, old), q in d["locked_inventory"].items()
                if d["bay_block"][i] == k and d["locked_release_local"].get((i, old), INF) > n
            )
            actual = sum(
                q
                for (i, j, _g), q in d["actual_inventory"].items()
                if d["bay_block"][i] == k and ship_present_at(d, j, n)
            )
            base_load[k, n] = locked + actual
    for j, g in sorted(d["remaining_demand"]):
        height = attrs[g]["height"]
        demand = d["remaining_demand"][j, g]
        profile = {n: d["forecast_arrivals"].get((j, g, n), 0) for n in periods}
        for k in d["blocks"]:
            capacity, height_conflicts, bay_free = 0, 0, []
            for i in d["bays_in_block"][k]:
                if not compatible(d, i, g):
                    continue
                locked = sum(
                    q
                    for (ii, old), q in d["locked_inventory"].items()
                    if ii == i and d["locked_release_local"].get((ii, old), INF) > last
                )
                actual = sum(
                    q
                    for (ii, ship, _g), q in d["actual_inventory"].items()
                    if ii == i and ship_present_at(d, ship, last)
                )
                fixed = {
                    h
                    for (ii, old), h in d["locked_height"].items()
                    if ii == i and d["locked_release_local"].get((ii, old), INF) > last
                } | {
                    attrs[gg]["height"]
                    for (ii, ship, gg), q in d["actual_inventory"].items()
                    if ii == i and q > 0 and ship_present_at(d, ship, last)
                }
                if fixed and height not in fixed:
                    height_conflicts += 1
                    continue
                free = max(0, d["capacity"][i] - locked - actual)
                capacity += free
                if free:
                    bay_free.append(free)
            left, estimated_bays = demand, 0
            for free in sorted(bay_free, reverse=True):
                if left <= 0:
                    break
                left -= free
                estimated_bays += 1
            if left > 0:
                estimated_bays += math.ceil(left / max(1, max(bay_free, default=1)))
            capacity_ratio = min(1.0, capacity / max(1, demand))
            distance = d["distance"][j, k] / max_dist
            overlap = sum(
                profile[n] * d["forecast_outbound"].get((k, n), 0) for n in periods
            ) / (max(1, demand) * max_out)
            balance_delta = 0.0
            for n in periods:
                loads = [base_load[kk, n] for kk in d["blocks"]]
                average = sum(loads) / len(loads)
                before = sum(abs(value - average) for value in loads)
                cumulative = sum(profile[t] for t in periods if t <= n)
                loads[d["blocks"].index(k)] += cumulative
                new_average = sum(loads) / len(loads)
                balance_delta += sum(abs(value - new_average) for value in loads) - before
            balance_delta /= max(1, demand * len(periods))
            bay_penalty = min(1.0, estimated_bays / 3)
            stability_loss = int(bool(old_blocks[j, g]) and k not in old_blocks[j, g])
            score = (
                IMPACT_SCORE_CAPACITY_WEIGHT * capacity_ratio
                - IMPACT_SCORE_DISTANCE_WEIGHT * distance
                - IMPACT_SCORE_OUTBOUND_WEIGHT * overlap
                - IMPACT_SCORE_BALANCE_WEIGHT * balance_delta
                - IMPACT_SCORE_BAY_WEIGHT * bay_penalty
                - IMPACT_SCORE_STABILITY_WEIGHT * stability_loss
            )
            scores[j, g, k] = {
                "score": score,
                "compatible_capacity": capacity,
                "capacity_ratio": capacity_ratio,
                "distance_normalized": distance,
                "outbound_overlap": overlap,
                "balance_delta": balance_delta,
                "estimated_bays": estimated_bays,
                "height_conflicts": height_conflicts,
                "stability_loss": stability_loss,
            }
    return scores


def _pair_resource_features(d: dict, scores: dict) -> dict[Pair, dict]:
    count = max(2, math.ceil(len(d["blocks"]) * DEPENDENCY_CANDIDATE_BLOCK_RATIO))
    features = {}
    for pair in sorted(d["remaining_demand"]):
        j, g = pair
        ranked = sorted(d["blocks"], key=lambda k: (-scores[j, g, k]["score"], k))
        old_blocks = {
            d["bay_block"][i]
            for (i, jj, gg), q in d["previous_reservation"].items()
            if jj == j and gg == g and q > 0
        }
        eligible = {k for k in d["blocks"] if scores[j, g, k]["compatible_capacity"] > 0}
        candidates = (set(ranked[:count]) | old_blocks) & eligible
        features[pair] = {
            "demand": d["remaining_demand"][pair],
            "size": d["group_attrs"][g]["size"],
            "height": d["group_attrs"][g]["height"],
            "arrival_profile": tuple(d["forecast_arrivals"].get((j, g, n), 0) for n in d["periods"]),
            "old_blocks": old_blocks,
            "eligible_blocks": eligible,
            "candidate_blocks": candidates,
            "compatible_capacity_by_block": {
                k: scores[j, g, k]["compatible_capacity"] for k in d["blocks"]
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
                min(a["compatible_capacity_by_block"][k], b["compatible_capacity_by_block"][k])
                for k in common
            )
            capacity_pressure = min(1.0, (a["demand"] + b["demand"]) / max(1, common_capacity))
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
    }


def _allowed(
    d: dict,
    level: int,
    direct_pairs: set[Pair],
    propagated_pairs: set[Pair],
    scores: dict,
    repair_pairs: set[Pair] | None = None,
) -> dict:
    result = {}
    repair_pairs = set(repair_pairs or ())
    affected = direct_pairs | propagated_pairs
    for pair in sorted(d["remaining_demand"]):
        j, g = pair
        old_blocks = {
            d["bay_block"][i]
            for (i, jj, gg), q in d["previous_reservation"].items()
            if jj == j and gg == g and q > 0
        }
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
            selected = old_blocks | set(ranked[:min(len(ranked), 1 + extra)])
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


def _quality_polish_allowed(
    d: dict,
    affected_pairs: set[Pair],
    direct_pairs: set[Pair],
    propagated_pairs: set[Pair],
    scores: dict,
    solution: dict,
) -> tuple[dict, dict]:
    allowed = _allowed(d, 0, direct_pairs, propagated_pairs, scores)
    reserve, din, attrs = solution["reservation"], solution["din"], d["group_attrs"]
    max_dist = max(d["distance"].values(), default=1)
    max_out = max(d["forecast_outbound"].values(), default=1)
    last = d["periods"][-1]
    final_load = {
        k: sum(
            q
            for (i, j, _g), q in d["actual_inventory"].items()
            if d["bay_block"][i] == k and ship_present_at(d, j, last)
        )
        + sum(
            q
            for (i, j, _g), q in reserve.items()
            if d["bay_block"][i] == k and ship_present_at(d, j, last)
        )
        for k in d["blocks"]
    }
    average = sum(final_load.values()) / max(1, len(final_load))
    contribution = {}
    for j, g in sorted(affected_pairs & set(d["remaining_demand"])):
        demand = max(1, d["remaining_demand"][j, g])
        used = [i for (i, jj, gg), q in reserve.items() if jj == j and gg == g and q > 1e-6]
        support = len({(attrs[g]["pod"], i) for i in used})
        distance = sum(
            d["distance"][j, d["bay_block"][i]] * q
            for (i, jj, gg, _n), q in din.items() if jj == j and gg == g
        ) / (demand * max_dist)
        overlap = sum(
            d["forecast_outbound"].get((d["bay_block"][i], n), 0) * q
            for (i, jj, gg, n), q in din.items() if jj == j and gg == g
        ) / (demand * max_out)
        overload = sum(
            max(0, final_load[d["bay_block"][i]] - average) * q
            for (i, jj, gg), q in reserve.items() if jj == j and gg == g
        ) / (demand * max(1, average))
        contribution[j, g] = 2 * support + distance + 2 * overlap + overload
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
    """Compute observable plan revisions without auxiliary-variable ambiguity."""
    old = d["previous_reservation"]
    cancellation = sum(max(0, q - reservation.get(key, 0)) for key, q in old.items())
    old_totals, current_totals = _pair_totals(old), d["remaining_demand"]
    pairs = set(old_totals) | set(current_totals)
    mandatory = sum(max(0, old_totals.get(pair, 0) - current_totals.get(pair, 0)) for pair in pairs)
    total_shortage = sum(shortage.values())
    discretionary = max(0, cancellation - mandatory - total_shortage)
    block_reallocation = 0.0
    for j, g in pairs:
        block_cancel = 0.0
        for k in d["blocks"]:
            old_block = _old_block_amount_for_plan(d, old, j, g, k)
            current_block = _old_block_amount_for_plan(d, reservation, j, g, k)
            block_cancel += max(0, old_block - current_block)
        pair_shortage = sum(q for (jj, gg, _n), q in shortage.items() if jj == j and gg == g)
        pair_mandatory = max(0, old_totals.get((j, g), 0) - current_totals.get((j, g), 0))
        block_reallocation += max(0, block_cancel - pair_mandatory - pair_shortage)
    attrs = d["group_attrs"]
    old_support = {(j, attrs[g]["pod"], i) for (i, j, g), q in old.items() if q > 1e-6}
    support = {(j, attrs[g]["pod"], i) for (i, j, g), q in reservation.items() if q > 1e-6}
    new_bays = len(support - old_support)
    stability_cost = (
        STABILITY_CANCEL_WEIGHT * cancellation
        + STABILITY_NEW_BAY_WEIGHT * new_bays
        + STABILITY_BLOCK_REALLOCATION_WEIGHT * block_reallocation
    )
    return {
        "cancellation_quantity": float(cancellation),
        "mandatory_reduction": float(mandatory),
        "discretionary_cancel": float(discretionary),
        "new_bay_count": float(new_bays),
        "block_reallocation_quantity": float(block_reallocation),
        "stability_cost": float(stability_cost),
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
    for name, expected in canonical.items():
        if name in solution.get("components", {}):
            record(f"{name}_accounting", abs(solution["components"][name] - expected))
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
    started = time.perf_counter()
    direct_pairs, direct_reasons = _direct_impact_pairs(d, impact_threshold)
    scores = _block_scores(d)
    dependency_graph, dependency_edges = {}, []
    if settings["dependency_propagation"]:
        dependency_graph, dependency_edges, _resource = _build_dependency_graph(d, scores)
        propagation = _propagate_impact_pairs(direct_pairs, dependency_graph)
    else:
        propagation = _propagate_impact_pairs(direct_pairs, {}, max_depth=0)
    propagated_pairs = set(propagation["propagated_pairs"])
    affected_pairs = set(propagation["affected_pairs"])
    diagnostic_path_scores = dict(propagation["best_path_score"])
    diagnostic_depths = dict(propagation["propagation_depth"])
    budget_info = _dynamic_stability_budget(d)
    incumbent = None;best_key = None;trace = [];solver_spent = 0.0
    repair_expansions = 0;quality_triggered = False;quality_improved = False
    repair_pairs: set[Pair] = set()
    if not settings["impact_region"]:
        stages = [(3, "global_core", None)]
    else:
        stages = [(0, "impact_region", None)]
    position = 0
    while position < len(stages):
        level, name, explicit_allowed = stages[position]
        remaining = max(0.0, time_limit - solver_spent)
        if remaining <= .1:
            break
        if explicit_allowed is not None:
            allowed = explicit_allowed
        elif level == 3:
            allowed = None
        else:
            allowed = _allowed(d, level, direct_pairs, propagated_pairs, scores, repair_pairs)
        budget = None
        if settings["impact_region"] and level < 3 and name != "quality_polish":
            budget = math.ceil(budget_info["allowance"] * (1, 1.5, 2.5)[min(level, 2)])
        if settings["progressive_repair"] and name == "impact_region":
            allocation = min(remaining, max(.1, .35 * time_limit))
        elif settings["progressive_repair"] and name.startswith("adaptive_repair"):
            allocation = min(remaining, max(.1, remaining / 2))
        else:
            allocation = remaining
        stage_started = time.perf_counter()
        model, variables, expressions = build_rolling_model(
            d, allowed_bays=allowed, shortage_allowed=True, stability_budget=budget
        )
        start_stats = _submit_start(variables, d, incumbent, enabled=settings["mip_start"])
        model.Params.OutputFlag = int(verbose);model.Params.Threads = threads;model.Params.Seed = seed
        model.Params.MIPGap = mip_gap;model.Params.TimeLimit = allocation;first = [None]
        def callback(m, where):
            if where == GRB.Callback.MIPSOL and first[0] is None:
                first[0] = time.perf_counter() - stage_started
        diagnostic_pairs = repair_pairs or affected_pairs
        ranking = {
            f"{j}|{g}": [
                {"block": k, **scores[j, g, k]}
                for k in sorted(d["blocks"], key=lambda k: (-scores[j, g, k]["score"], k))[:3]
            ]
            for j, g in sorted(diagnostic_pairs & set(d["remaining_demand"]))
        }
        model.optimize(callback)
        run_time = float(model.Runtime);solver_spent += run_time
        record = {
            "stage": name,
            "neighborhood_level": level,
            "stability_budget": budget,
            "stability_budget_disabled": budget is None,
            "allocated_solver_time": allocation,
            "cumulative_solver_time": solver_spent,
            "expanded_shortage_pairs": [list(pair) for pair in sorted(repair_pairs)],
            "top_block_scores": ranking,
            "direct_pair_count": len(direct_pairs),
            "propagated_pair_count": len(propagated_pairs),
            "affected_pair_count": len(affected_pairs),
            "allowed_pair_bay_count": sum(len(value) for value in allowed.values()) if allowed else sum(1 for i in d["bays"] for j, g in d["remaining_demand"] if compatible(d, i, g)),
            "dependency_expansion_count": len(propagated_pairs),
            "status": int(model.Status),
            "runtime": run_time,
            "nodes": float(model.NodeCount),
            "variables": int(model.NumVars),
            "constraints": int(model.NumConstrs),
            "has_solution": bool(model.SolCount),
            "first_incumbent_time": first[0],
            "mip_start": start_stats,
        }
        previous_key = best_key
        if model.SolCount:
            candidate = extract_rolling_solution(variables, expressions)
            candidate["components"].update(canonical_stability_metrics(d, candidate["reservation"], candidate["shortage"]))
            c = candidate["components"]
            key = (round(c["predicted_shortage"], 6), round(c["stability_cost"], 6), round(c["operations_cost"], 9))
            record.update({name: c[name] for name in (
                "predicted_shortage", "cancellation_quantity", "mandatory_reduction",
                "discretionary_cancel", "new_bay_count", "block_reallocation_quantity",
                "stability_cost", "operations_cost", "in_out_conflict_raw"
            )})
            record["stability_budget_binding"] = budget is not None and c["discretionary_cancel"] >= budget - 1e-6
            if best_key is None or key < best_key:
                incumbent, best_key = candidate, key
            if name == "quality_polish":
                quality_improved = previous_key is None or best_key < previous_key
        trace.append(record);position += 1
        if not settings["progressive_repair"]:
            continue
        shortage_pairs = {
            (j, g) for (j, g, _n), q in (incumbent or {}).get("shortage", {}).items() if q > 1e-6
        }
        remaining = max(0.0, time_limit - solver_spent)
        if incumbent and incumbent["components"]["predicted_shortage"] <= 1e-6:
            if settings["quality_polish"] and name != "quality_polish" and remaining > .1:
                polish_allowed, info = _quality_polish_allowed(
                    d, affected_pairs, direct_pairs, propagated_pairs, scores, incumbent
                )
                quality_triggered = True;stages.append((0, "quality_polish", polish_allowed))
                record["quality_polish_plan"] = info
            continue
        if shortage_pairs:
            for pair in shortage_pairs:
                direct_pairs.add(pair);direct_reasons.setdefault(pair, []).append("shortage_repair")
                diagnostic_path_scores[pair] = max(1.0, diagnostic_path_scores.get(pair, 0.0))
                diagnostic_depths[pair] = 0
            propagated_pairs -= shortage_pairs
            repair_pairs |= shortage_pairs;affected_pairs |= shortage_pairs
            if settings["dependency_propagation"]:
                repair_prop = _propagate_impact_pairs(shortage_pairs, dependency_graph, max_depth=1)
                new_neighbors = set(repair_prop["propagated_pairs"]) - direct_pairs
                propagated_pairs |= new_neighbors;affected_pairs |= new_neighbors;repair_pairs |= new_neighbors
                for pair in sorted(new_neighbors):
                    score = repair_prop["best_path_score"][pair]
                    if score > diagnostic_path_scores.get(pair, -1):
                        diagnostic_path_scores[pair] = score
                        diagnostic_depths[pair] = repair_prop["propagation_depth"][pair]
        if name == "impact_region":
            stages.append((1, "adaptive_repair_1", None));repair_expansions += 1
        elif name == "adaptive_repair_1":
            stages.append((2, "adaptive_repair_2", None));repair_expansions += 1
        elif name == "adaptive_repair_2":
            stages.append((3, "global_repair", None));repair_expansions += 1
    report = validate_rolling_solution(d, incumbent) if incumbent else None
    top_edges = dependency_edges[:20]
    path_scores = {
        f"{j}|{g}": score
        for (j, g), score in sorted(diagnostic_path_scores.items())
    }
    impact_diagnostics = {
        "direct_pairs": [list(pair) for pair in sorted(direct_pairs)],
        "direct_reasons": {f"{j}|{g}": reasons for (j, g), reasons in sorted(direct_reasons.items())},
        "propagated_pairs": [list(pair) for pair in sorted(propagated_pairs)],
        "affected_pairs": [list(pair) for pair in sorted(affected_pairs)],
        "propagation_enabled": settings["dependency_propagation"],
        "max_depth_reached": max(diagnostic_depths.values(), default=0),
        "dependency_edge_count": len(dependency_edges),
        "top_dependency_edges": top_edges,
        "path_scores": path_scores,
    }
    return {
        "ok": bool(incumbent and report["feasible"]),
        "configuration": configuration,
        "solution": incumbent,
        "validation": report,
        "affected_ships": sorted({j for j, _g in affected_pairs}),
        "impact_diagnostics": impact_diagnostics,
        "stability_budget_diagnostics": budget_info,
        "stages": trace,
        "repair_triggered": settings["progressive_repair"] and repair_expansions > 0,
        "repair_expansions": repair_expansions,
        "quality_polish_triggered": quality_triggered,
        "quality_polish_improved": quality_improved,
        "runtime": time.perf_counter() - started,
        "final_stage": trace[-1]["stage"] if trace else None,
    }

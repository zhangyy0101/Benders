"""Deterministic aggregate-guided candidate block and bay domains."""
from __future__ import annotations

import math
import time

import gurobipy as gp
from gurobipy import GRB

from model_common import arrival, fixed_in_block, group_size, outbound_pressure, remaining_capacity, required_reserve, ship_groups


TOLERANCE = 1e-7


def _stable(value):
    return str(value)


def _compatible_bays(data, group):
    size = group_size(data, group)
    return sorted((i for i in data["I_list"] if int(data["Fixed_Bay_Mode"][i]) == size), key=_stable)


def _guide_maps(guide_result):
    diagnostics = guide_result.get("diagnostics") or {}
    return (
        diagnostics.get("aggregate_flow_by_ship_size_block", {}),
        diagnostics.get("alloc_support_by_ship_group_bay", {}),
        diagnostics.get("x_support_by_ship_bay", {}),
    )


def _resource_metrics(data, j, group, i, rem, pressure):
    alpha = float(data["Alpha"])
    block = data["I"][i]["block"]
    reserve_ratios, handling_ratios, reserve_slacks, handling_slacks = [], [], [], []
    relevant_pressure = []
    for n in data["N"]:
        reserve = float(required_reserve(data, j, group, n, "continuous"))
        arrivals = float(arrival(data, j, group, n))
        handling = float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"])
        if reserve > TOLERANCE:
            reserve_ratios.append(rem[i, n] / reserve)
            reserve_slacks.append(rem[i, n] - reserve)
        if arrivals > TOLERANCE:
            need = alpha * arrivals
            handling_ratios.append(handling / need)
            handling_slacks.append(handling - need)
            relevant_pressure.append(float(pressure[block, n]))
    return {
        "min_reserve_slack_ratio": min(reserve_ratios, default=float("inf")),
        "min_handling_slack_ratio": min(handling_ratios, default=float("inf")),
        "mean_reserve_slack": sum(reserve_slacks) / max(1, len(reserve_slacks)),
        "mean_handling_slack": sum(handling_slacks) / max(1, len(handling_slacks)),
        "distance": float(data["Dist"][j, block]),
        "pressure": sum(relevant_pressure) / max(1, len(relevant_pressure)),
    }


def _individual_coverage(data, j, group, bays, rem):
    alpha = float(data["Alpha"])
    failures = []
    for n in data["N"]:
        reserve_capacity = sum(float(rem[i, n]) for i in bays)
        reserve_need = float(required_reserve(data, j, group, n, "continuous"))
        handling_capacity = sum(
            float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"])
            for i in bays
        )
        handling_need = alpha * float(arrival(data, j, group, n))
        if reserve_capacity + TOLERANCE < reserve_need:
            failures.append({"period": n, "resource": "reserve", "capacity": reserve_capacity, "need": reserve_need})
        if handling_capacity + TOLERANCE < handling_need:
            failures.append({"period": n, "resource": "handling", "capacity": handling_capacity, "need": handling_need})
    return not failures, failures


def check_joint_candidate_feasibility(data, candidate_bays, *, time_limit: float = 2.0, threads: int = 1,
                                      integer_reserve: bool = False) -> dict:
    """Check necessary joint feasibility using a continuous, objective-free LP."""
    started = time.perf_counter()
    if time_limit <= 0:
        return {"status": "unknown", "status_name": "NOT_SOLVED", "runtime": 0.0}
    model = gp.Model("candidate_domain_joint_coverage")
    try:
        model.Params.OutputFlag = 0
        model.Params.Threads = int(threads or 1)
        model.Params.TimeLimit = max(0.0, float(time_limit))
        pairs = [(j, g) for j in data["J_new"] for g in ship_groups(data, j)]
        keys = [(i, j, g, n) for j, g in pairs for i in candidate_bays[j, g] for n in data["N"]]
        reserve = model.addVars(keys, lb=0, vtype=GRB.INTEGER if integer_reserve else GRB.CONTINUOUS, name="reserve")
        flow = model.addVars([(j, g, i, n) for i, j, g, n in keys], lb=0, name="flow")
        inventory = model.addVars([(j, g, i, n) for i, j, g, n in keys], lb=0, name="inventory")
        alpha = float(data["Alpha"])
        rem = remaining_capacity(data)
        for j, g in pairs:
            bays = candidate_bays[j, g]
            for n in data["N"]:
                reserve_domain = "integer" if integer_reserve else "continuous"
                model.addConstr(gp.quicksum(reserve[i, j, g, n] for i in bays) == required_reserve(data, j, g, n, reserve_domain))
                model.addConstr(gp.quicksum(flow[j, g, i, n] for i in bays) == arrival(data, j, g, n))
                for i in bays:
                    previous = inventory[j, g, i, n - 1] if n > 0 else float(data["initial_inventory_data"].get((i, j, g), 0))
                    model.addConstr(inventory[j, g, i, n] == previous + flow[j, g, i, n])
                    model.addConstr(alpha * inventory[j, g, i, n] <= reserve[i, j, g, n])
        for i in data["I_list"]:
            for n in data["N"]:
                reserve_terms = [reserve[i, j, g, n] for j, g in pairs if i in candidate_bays[j, g]]
                if reserve_terms:
                    model.addConstr(gp.quicksum(reserve_terms) <= rem[i, n])
            for j in data["J_new"]:
                groups = [g for g in ship_groups(data, j) if i in candidate_bays[j, g]]
                for n in data["N"]:
                    if groups:
                        capacity = float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"])
                        model.addConstr(alpha * gp.quicksum(flow[j, g, i, n] for g in groups) <= capacity)
        model.setObjective(0.0)
        model.optimize()
        status = "feasible" if model.SolCount else "infeasible" if model.Status == GRB.INFEASIBLE else "unknown"
        name = {GRB.OPTIMAL: "OPTIMAL", GRB.INFEASIBLE: "INFEASIBLE", GRB.TIME_LIMIT: "TIME_LIMIT"}.get(model.Status, str(model.Status))
        partial_start = None
        full_start = None
        if model.SolCount:
            alloc_start = {}
            x_start = {}
            reserve_support = {}
            for i, j, g, n in keys:
                value = float(reserve[i, j, g, n].X)
                if value > TOLERANCE:
                    x_start[i, j, n] = 1.0
                    item = reserve_support.setdefault((j, g, i), {"max": 0.0, "sum": 0.0})
                    item["max"] = max(item["max"], value); item["sum"] += value
                    if abs(value - round(value)) <= 1e-7:
                        alloc_start[i, j, g, n] = float(round(value))
            partial_start = {"x": x_start, "alloc_boxes": alloc_start}
            if integer_reserve:
                alloc_values = {(i, j, g, n): float(reserve[i, j, g, n].X) for i, j, g, n in keys}
                flow_values = {(j, g, i, n): float(flow[j, g, i, n].X) for i, j, g, n in keys}
                inventory_values = {(j, g, i, n): float(inventory[j, g, i, n].X) for i, j, g, n in keys}
                x_values = {(i, j, n): float(any(alloc_values.get((i, j, g, n), 0) > TOLERANCE
                                                        for g in ship_groups(data, j)))
                            for j in data["J_new"] for i in {bay for g in ship_groups(data, j) for bay in candidate_bays[j, g]}
                            for n in data["N"]}
                share_values = {(j, k, g, n): sum(flow_values.get((j, g, i, n), 0.0) for i in data["Bays_in_Block"][k])
                                for j, g in pairs for k in data["K"] for n in data["N"]}
                fixed = fixed_in_block(data)
                total_values = {(k, n): fixed[k, n] + sum(share_values[j, k, g, n] for j, g in pairs)
                                for k in data["K"] for n in data["N"]}
                avg_values = {n: sum(total_values[k, n] for k in data["K"]) / len(data["K"]) for n in data["N"]}
                balance_values = {(k, n): abs(total_values[k, n] - avg_values[n]) for k in data["K"] for n in data["N"]}
                final = max(data["N"])
                use_values = {(j, g, i): float(alloc_values.get((i, j, g, final), 0) > TOLERANCE)
                              for j, g in pairs for i in candidate_bays[j, g]}
                full_start = {"x": x_values, "alloc_boxes": alloc_values, "din": flow_values,
                              "inv": inventory_values, "in_share": share_values, "in_total": total_values,
                              "avg": avg_values, "g_bal": balance_values, "concentration_use": use_values}
        return {"status": status, "status_name": name, "runtime": time.perf_counter() - started,
                "variable_count": model.NumVars, "constraint_count": model.NumConstrs,
                "partial_start": partial_start, "full_start": full_start,
                "reserve_support": reserve_support if model.SolCount else {}}
    except Exception as exc:
        return {"status": "unknown", "status_name": "ERROR", "runtime": time.perf_counter() - started,
                "error": f"{type(exc).__name__}: {exc}"}
    finally:
        model.dispose()


def build_candidate_domain(
    data,
    guide_result,
    *,
    block_mass_target: float = 0.90,
    min_blocks_per_ship_size: int = 2,
    max_blocks_per_ship_size: int = 4,
    min_bays_per_group: int = 3,
    max_bays_per_group: int = 12,
    max_candidate_fraction: float = 0.40,
    expansion_level: int = 0,
    auto_expand_joint: bool = True,
    joint_time_limit: float = 2.0,
) -> dict:
    if not 0 <= block_mass_target <= 1 or not 0 <= max_candidate_fraction <= 1:
        raise ValueError("mass target and candidate fraction must lie in [0, 1]")
    if not 0 <= expansion_level <= 2:
        raise ValueError("expansion_level must be 0, 1, or 2")
    if min_blocks_per_ship_size < 1 or max_blocks_per_ship_size < min_blocks_per_ship_size:
        raise ValueError("invalid block limits")
    if min_bays_per_group < 1 or max_bays_per_group < min_bays_per_group:
        raise ValueError("invalid bay limits")

    rem = remaining_capacity(data)
    pressure = outbound_pressure(data)
    z_support, alloc_support, x_support = _guide_maps(guide_result)
    block_scores, bay_scores = {}, {}
    block_rankings, candidate_blocks = {}, {}

    for j in data["J_new"]:
        for size in sorted((int(s) for s in data["S"])):
            groups = [g for g in ship_groups(data, j) if group_size(data, g) == size]
            if not groups:
                continue
            rows = []
            total_z = sum(max(0.0, float(z_support.get((j, size, k), 0.0))) for k in data["K"])
            for k in data["K"]:
                bays = [i for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i]) == size]
                z = max(0.0, float(z_support.get((j, size, k), 0.0)))
                alloc = sum(float(alloc_support.get((j, g, i), {}).get("max", 0.0)) for g in groups for i in bays)
                xs = sum(float(x_support.get((j, i), 0.0)) for i in bays)
                relevant = [n for n in data["N"] if any(arrival(data, j, g, n) > TOLERANCE for g in groups)]
                capacity = min((sum(rem[i, n] for i in bays) for n in data["N"]), default=0.0)
                handling = min((sum(float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"]) for i in bays) for n in relevant), default=0.0)
                dist = float(data["Dist"][j, k])
                press = sum(float(pressure[k, n]) for n in relevant) / max(1, len(relevant))
                score = {"z": z, "alloc": alloc, "x": xs, "normalized_z": z / total_z if total_z > TOLERANCE else 0.0,
                         "capacity_slack": capacity, "handling_slack": handling, "distance": dist, "pressure": press}
                block_scores[j, size, k] = score
                key = (-int(z > TOLERANCE), -int(alloc > TOLERANCE), -int(xs > TOLERANCE), -score["normalized_z"],
                       -capacity, -handling, dist, press, _stable(k))
                rows.append((key, k))
            ranking = [k for _, k in sorted(rows)]
            block_rankings[j, size] = ranking
            positive_z = [k for k in ranking if block_scores[j, size, k]["z"] > TOLERANCE]
            selected = []
            cumulative = 0.0
            target = 1.0 if expansion_level >= 2 else block_mass_target
            for k in positive_z:
                if total_z > TOLERANCE and cumulative / total_z >= target - TOLERANCE:
                    break
                selected.append(k)
                cumulative += block_scores[j, size, k]["z"]
            for k in ranking:
                if block_scores[j, size, k]["alloc"] > TOLERANCE and k not in selected:
                    selected.append(k)
            desired_min = min(len(ranking), min_blocks_per_ship_size + (1 if expansion_level >= 1 else 0))
            for k in ranking:
                if len(selected) >= desired_min:
                    break
                if k not in selected:
                    selected.append(k)
            protected = {k for k in selected if block_scores[j, size, k]["alloc"] > TOLERANCE}
            limit = min(len(ranking), max_blocks_per_ship_size + (1 if expansion_level >= 1 else 0))
            selected = [k for k in ranking if k in protected or (k in selected and ranking.index(k) < limit)]
            backup = next((k for k in ranking if k not in selected), None)
            if backup is not None:
                selected.append(backup)
            if expansion_level >= 1:
                next_block = next((k for k in ranking if k not in selected), None)
                if next_block is not None:
                    selected.append(next_block)
            candidate_blocks[j, size] = sorted(selected, key=lambda k: ranking.index(k))

    candidate_bays, bay_rankings = {}, {}
    forced_exceptions = []
    individual_details = {}
    for j in data["J_new"]:
        for group in ship_groups(data, j):
            size = group_size(data, group)
            selected_blocks = candidate_blocks[j, size]
            block_positions = {k: p for p, k in enumerate(block_rankings[j, size])}
            rows = []
            for i in _compatible_bays(data, group):
                block = data["I"][i]["block"]
                support = alloc_support.get((j, group, i), {})
                metrics = _resource_metrics(data, j, group, i, rem, pressure)
                score = {"alloc_support": float(support.get("max", 0.0)), "alloc_mass": float(support.get("sum", 0.0)),
                         "x_support": float(x_support.get((j, i), 0.0)), "block": block,
                         "block_rank": block_positions[block], **metrics}
                bay_scores[j, group, i] = score
                key = (-int(score["alloc_support"] > TOLERANCE), -int(score["x_support"] > TOLERANCE),
                       -int(block in selected_blocks), score["block_rank"], -score["min_reserve_slack_ratio"],
                       -score["min_handling_slack_ratio"], score["distance"], score["pressure"], _stable(i))
                rows.append((key, i))
            ranking = [i for _, i in sorted(rows)]
            bay_rankings[j, group] = ranking
            chosen = [i for i in ranking if bay_scores[j, group, i]["alloc_support"] > TOLERANCE]
            target_count = min(len(ranking), min_bays_per_group + (2 if expansion_level >= 1 else 0) + (3 if expansion_level >= 2 else 0))
            selected_block_bays = [i for i in ranking if data["I"][i]["block"] in selected_blocks]
            selection_order = selected_block_bays + ranking
            if guide_result.get("source") == "static_fallback" and ranking:
                peers = [g for g in ship_groups(data, j) if group_size(data, g) == size]
                offset = (peers.index(group) * max(1, target_count)) % len(ranking)
                rotated = ranking[offset:] + ranking[:offset]
                selection_order = ([i for i in rotated if data["I"][i]["block"] in selected_blocks] + rotated)
            for i in selection_order:
                if len(chosen) >= target_count:
                    break
                if i not in chosen:
                    chosen.append(i)
            passed, failures = _individual_coverage(data, j, group, chosen, rem)
            cursor = 0
            while not passed and cursor < len(ranking):
                i = ranking[cursor]
                cursor += 1
                if i not in chosen:
                    chosen.append(i)
                    passed, failures = _individual_coverage(data, j, group, chosen, rem)
            soft_fraction = 0.60 if expansion_level >= 2 else max_candidate_fraction
            soft_cap = min(max_bays_per_group, max(min_bays_per_group, math.ceil(soft_fraction * len(ranking))))
            if len(chosen) > soft_cap:
                forced_exceptions.append({"ship": j, "group": group, "soft_cap": soft_cap, "actual": len(chosen),
                                          "reason": "guide_support" if any(bay_scores[j, group, i]["alloc_support"] > TOLERANCE for i in chosen[soft_cap:]) else "individual_coverage"})
            candidate_bays[j, group] = sorted(chosen, key=lambda i: ranking.index(i))
            individual_details[j, group] = {"passed": passed, "failures": failures}

    # A proven joint infeasibility triggers one deterministic full-compatible expansion.
    # This avoids making the returned domain depend on the timing of several successive LPs.
    # A timeout remains unknown and never triggers expansion.
    joint = check_joint_candidate_feasibility(data, candidate_bays, time_limit=joint_time_limit)
    expansion_rounds = 0
    if auto_expand_joint and joint["status"] == "infeasible":
        changed = any(len(candidate_bays[key]) < len(ranking) for key, ranking in bay_rankings.items())
        if changed:
            candidate_bays = {key: list(ranking) for key, ranking in bay_rankings.items()}
            expansion_rounds = 1
            forced_exceptions.append({"reason": "joint_coverage", "action": "full_compatible_expansion"})
            joint = check_joint_candidate_feasibility(data, candidate_bays, time_limit=joint_time_limit)

    candidate_ship_bays = {(i, j) for (j, _g), bays in candidate_bays.items() for i in bays}
    full_pairs = sum(len(_compatible_bays(data, g)) for j in data["J_new"] for g in ship_groups(data, j))
    candidate_pairs = sum(len(bays) for bays in candidate_bays.values())
    diagnostics = {
        "guide_source": guide_result.get("source", "static_fallback"),
        "block_count_by_ship_size": {key: len(value) for key, value in candidate_blocks.items()},
        "bay_count_by_ship_group": {key: len(value) for key, value in candidate_bays.items()},
        "candidate_group_bay_pair_count": candidate_pairs,
        "full_group_bay_pair_count": full_pairs,
        "candidate_pair_ratio": candidate_pairs / max(1, full_pairs),
        "candidate_ship_bay_pair_count": len(candidate_ship_bays),
        "individual_coverage_pass": all(item["passed"] for item in individual_details.values()),
        "joint_coverage_status": joint["status"],
        "expansion_level": expansion_level,
        "joint_expansion_rounds": expansion_rounds,
        "forced_soft_cap_exceptions": forced_exceptions,
    }
    return {
        "candidate_blocks": candidate_blocks,
        "candidate_bays": candidate_bays,
        "candidate_ship_bays": candidate_ship_bays,
        "coverage": {"individual": individual_details, "joint": joint},
        "scores": {"blocks": block_scores, "bays": bay_scores, "block_rankings": block_rankings, "bay_rankings": bay_rankings},
        "diagnostics": diagnostics,
    }

"""Algorithm-independent objective, feasibility, and operational KPI evaluation."""
from __future__ import annotations

import math

from model_common import (
    arrival,
    group_size,
    groups,
    objective_scales,
    old_occupancy,
    outbound_pressure,
    scale_factor,
)
from model_concentration import evaluate_joint_group_concentration

def validate_solution(data,solution,*,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,tolerance=1e-5):
    """Independent feasibility checker for exact incumbent solutions."""
    from model_common import arrival,fixed_in_block,group_attr,group_size,groups,remaining_capacity,required_reserve,ship_group_pairs,ship_groups
    from model_concentration import evaluate_joint_group_concentration
    I,J,N,K=data["I_list"],data["J_new"],data["N"],data["K"];pairs=ship_group_pairs(data);rem=remaining_capacity(data);viol={}
    def rec(name,x):viol[name]=max(viol.get(name,0),max(0,float(x)))
    def val(name,k):return float(solution.get(name,{}).get(k,0))
    for j in J:
     for g in ship_groups(data,j):
      for n in N:
       rec("arrival",abs(sum(val("din",(j,g,i,n)) for i in I)-arrival(data,j,g,n)));rec("exact_reserve",abs(sum(val("alloc_boxes",(i,j,g,n)) for i in I)-required_reserve(data,j,g,n,alloc_domain)))
       for i in I:
        cumulative=float(data["initial_inventory_data"].get((i,j,g),0))+sum(val("din",(j,g,i,t)) for t in N if t<=n);rec("inventory_derived",abs(val("inv",(j,g,i,n))-cumulative));rec("storage_link",cumulative-val("alloc_boxes",(i,j,g,n)));rec("fixed_mode",abs(val("alloc_boxes",(i,j,g,n))) if group_size(data,g)!=int(data["Fixed_Bay_Mode"][i]) else 0)
     for k in K:
      for g in ship_groups(data,j):
       for n in N:rec("block_flow",abs(val("in_share",(j,k,g,n))-sum(val("din",(j,g,i,n)) for i in data["Bays_in_Block"][k])))
    fixed=fixed_in_block(data)
    for i in I:
     used={group_attr(data,g,"height") for j,g in pairs if any(val("alloc_boxes",(i,j,g,n))>tolerance for n in N)};old=data.get("OldBayHeight",{}).get(i);rec("height_mixing",len(used|({old} if old is not None else set()))-1)
     for n in N:rec("bay_capacity",sum(val("alloc_boxes",(i,j,g,n)) for j,g in pairs)-rem[i,n])
    for k in K:
     for n in N:rec("in_total",abs(val("in_total",(k,n))-fixed[k,n]-sum(val("in_share",(j,k,g,n)) for j,g in pairs)));rec("l1_pos",val("in_total",(k,n))-val("avg",n)-val("g_bal",(k,n)));rec("l1_neg",val("avg",n)-val("in_total",(k,n))-val("g_bal",(k,n)))
    for n in N:rec("average",abs(len(K)*val("avg",n)-sum(val("in_total",(k,n)) for k in K)))
    if alloc_domain=="integer":
     for value in solution["alloc_boxes"].values():rec("integrality",abs(value-round(value)))
    concentration=evaluate_joint_group_concentration(data,solution,alloc_domain=alloc_domain,enabled=concentration_enabled,tolerance=tolerance)
    if concentration["enabled"] and "concentration_use" in solution:
     for (j,g,i),value in solution["concentration_use"].items():rec("concentration_support",abs(float(value)-float(i in concentration["used_bays"].get((j,g),[]))))
     rec("concentration_raw",abs(sum(float(v) for v in solution["concentration_use"].values())-concentration["raw_used_bays"]))
    maximum=max(viol.values(),default=0);return {"feasible":maximum<=tolerance,"max_violation":maximum,"violations_by_family":viol}

REQUIRED_SOLUTION_FIELDS = (
    "x", "alloc_boxes", "din", "inv", "in_share", "in_total", "avg", "g_bal",
)


def _percentile(values, fraction):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _utilization_metrics(occupancy, capacities):
    ratios = []
    remaining = []
    for key, value in occupancy.items():
        capacity = float(capacities[key])
        remaining.append(capacity - float(value))
        if capacity > 0:
            ratios.append(float(value) / capacity)
    return {
        "mean": sum(ratios) / len(ratios) if ratios else None,
        "max": max(ratios, default=None),
        "p95": _percentile(ratios, .95),
        "ratio_above_80_percent": sum(value > .8 for value in ratios) / len(ratios) if ratios else None,
        "ratio_above_90_percent": sum(value > .9 for value in ratios) / len(ratios) if ratios else None,
        "minimum_remaining_boxes": min(remaining, default=None),
    }


def evaluate_common_solution(
    data,
    weights,
    solution,
    *,
    alloc_domain="integer",
    concentration_enabled=True,
    tolerance=1e-5,
):
    """Evaluate one standard solution without consulting a solver or solver state."""
    if not isinstance(solution, dict):
        raise TypeError("solution must be a dictionary")
    missing = [name for name in REQUIRED_SOLUTION_FIELDS if not isinstance(solution.get(name), dict)]
    complete = not missing
    from model_common import ship_group_pairs,ship_groups
    I, J, G, N, K = data["I_list"], data["J_new"], groups(data), data["N"], data["K"];pairs=ship_group_pairs(data)
    scales = objective_scales(data)
    factor = scale_factor(weights)
    x = solution.get("x", {})
    alloc = solution.get("alloc_boxes", {})
    share = solution.get("in_share", {})
    balance_values = solution.get("g_bal", {})

    arrivals_by_ship = {j: sum(arrival(data, j, g, n) for g in ship_groups(data,j) for n in N) for j in J}
    arrivals_by_size = {
        str(size): sum(arrival(data, j, g, n) for j,g in pairs for n in N if group_size(data, g) == int(size))
        for size in data["S"]
    }
    period_arrivals = {n: sum(arrival(data, j, g, n) for j,g in pairs) for n in N}
    active_periods = [n for n in N if period_arrivals[n] > tolerance]
    total_arrivals = sum(arrivals_by_ship.values())

    open_raw = sum(float(x.get((i, j, n), 0)) * float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N)
    open_counts = {n: sum(float(x.get((i, j, n), 0)) > tolerance for i in I for j in J) for n in N}
    concentration = evaluate_joint_group_concentration(
        data, solution, alloc_domain=alloc_domain, enabled=concentration_enabled, tolerance=tolerance,
    )
    bays_per_group = [len(concentration["used_bays"].get(pair, [])) for pair in concentration["positive_ship_groups"]] if concentration["enabled"] else []

    pressure = outbound_pressure(data)
    distance_raw = sum(float(data["Dist"][j, k]) * float(share.get((j, k, g, n), 0)) for j,g in pairs for k in K for n in N)
    balance_raw = sum(float(value) for value in balance_values.values())
    conflict_by_period = {
        n: sum(float(pressure[k, n]) * float(share.get((j, k, g, n), 0)) for j,g in pairs for k in K)
        for n in N
    }
    conflict_raw = sum(conflict_by_period.values())
    positive_pressure_boxes = sum(
        float(share.get((j, k, g, n), 0))
        for j,g in pairs for k in K for n in N if pressure[k, n] > tolerance
    )

    workloads = {n: [float(solution.get("in_total", {}).get((k, n), 0)) for k in K] for n in N}
    workload_cvs = []
    active_workloads = []
    for n, values in workloads.items():
        mean = sum(values) / len(values) if values else 0
        if mean > tolerance:
            workload_cvs.append((sum((value - mean) ** 2 for value in values) / len(values)) ** .5 / mean)
            active_workloads.extend(values)
    peak_workload = max((value for values in workloads.values() for value in values), default=0)
    mean_active_workload = sum(active_workloads) / len(active_workloads) if active_workloads else 0

    old = old_occupancy(data)
    capacities = {(i, n): float(data["I"][i]["cap"]) for i in I for n in N}
    reserved_occupancy = {
        (i, n): old.get((i, n), 0) + sum(float(alloc.get((i, j, g, n), 0)) for j,g in pairs)
        for i in I for n in N
    }
    physical_occupancy = None if "inv" not in solution else {
        (i, n): old.get((i, n), 0) + sum(float(solution["inv"].get((j, g, i, n), 0)) for j,g in pairs)
        for i in I for n in N
    }

    concentration_normalized = concentration["normalized"] if concentration["enabled"] else None
    weighted = {
        "open": factor * weights.master.x * open_raw / scales["open"],
        "concentration": 0.0 if not concentration["enabled"] else factor * weights.master.concentration * concentration_normalized,
        "distance": factor * weights.sub.dist * distance_raw / scales["distance"],
        "balance": factor * weights.sub.balance * balance_raw / scales["balance"],
        "conflict": factor * weights.sub.conflict * conflict_raw / scales["conflict"],
    }
    normalized = {
        "open": open_raw / scales["open"],
        "concentration": concentration_normalized,
        "distance": distance_raw / scales["distance"],
        "balance": balance_raw / scales["balance"],
        "conflict": conflict_raw / scales["conflict"],
    }
    components = {
        name: {"raw": raw, "scale": scales.get(name, concentration.get("scale")), "normalized": normalized[name], "weighted": weighted[name]}
        for name, raw in {
            "open": open_raw, "concentration": concentration["raw_used_bays"], "distance": distance_raw,
            "balance": balance_raw, "conflict": conflict_raw,
        }.items()
    }
    first_stage = weighted["open"] + weighted["concentration"]
    recourse = weighted["distance"] + weighted["balance"] + weighted["conflict"]
    feasibility = validate_solution(
        data, solution, alloc_domain=alloc_domain, concentration_enabled=concentration_enabled,
        tolerance=tolerance,
    ) if complete else {
        "feasible": False,
        "max_violation": None,
        "violations_by_family": {},
        "reason": "incomplete solution",
    }
    feasibility["evaluation_incomplete"] = not complete
    feasibility["missing_solution_fields"] = missing

    kpis = {
        "volume": {"total_new_arrival_boxes": total_arrivals, "by_ship": arrivals_by_ship, "by_size": arrivals_by_size, "active_period_count": len(active_periods)},
        "open_usage": {
            "open_bay_hours": open_raw,
            "open_bay_ship_period_count": sum(open_counts.values()),
            "peak_open_pairs_per_period": max(open_counts.values(), default=0),
            "mean_open_pairs_per_active_period": sum(open_counts[n] for n in active_periods) / len(active_periods) if active_periods else 0.0,
        },
        "concentration": {
            "availability": concentration["available"], "enabled": concentration["enabled"], "status": concentration["status"],
            "joint_group_bay_usage_total": concentration["raw_used_bays"],
            "positive_ship_group_count": len(concentration["positive_ship_groups"]),
            "mean_bays_per_positive_ship_group": sum(bays_per_group) / len(bays_per_group) if bays_per_group else None,
            "max_bays_per_positive_ship_group": max(bays_per_group, default=None),
            "single_bay_ship_group_ratio": sum(value == 1 for value in bays_per_group) / len(bays_per_group) if bays_per_group else None,
            "normalized": concentration_normalized,
        },
        "distance": {"distance_total": distance_raw, "distance_per_arrival_box": distance_raw / total_arrivals if total_arrivals > tolerance else 0.0},
        "workload": {
            "workload_l1_total": balance_raw,
            "workload_cv_mean_active_periods": sum(workload_cvs) / len(workload_cvs) if workload_cvs else 0.0,
            "workload_cv_max_active_periods": max(workload_cvs, default=0.0),
            "peak_block_workload": peak_workload,
            "peak_to_mean_block_workload_ratio": peak_workload / mean_active_workload if mean_active_workload > tolerance else 0.0,
        },
        "conflict": {
            "conflict_weighted_total": conflict_raw,
            "conflict_per_arrival_box": conflict_raw / total_arrivals if total_arrivals > tolerance else 0.0,
            "boxes_assigned_to_positive_pressure_blocks": positive_pressure_boxes,
            "positive_pressure_assignment_ratio": positive_pressure_boxes / total_arrivals if total_arrivals > tolerance else 0.0,
            "max_period_conflict_weighted_flow": max(conflict_by_period.values(), default=0.0),
        },
        "utilization": {
            "reserved": _utilization_metrics(reserved_occupancy, capacities),
            "physical": None if physical_occupancy is None else _utilization_metrics(physical_occupancy, capacities),
        },
    }
    result = {
        "feasibility": feasibility,
        "objective": {"total": first_stage + recourse, "first_stage": first_stage, "recourse": recourse},
        "components": components,
        "kpis": kpis,
        "metadata": {
            "evaluation_incomplete": not complete,
            "alloc_domain": alloc_domain,
            "concentration_enabled_requested": bool(concentration_enabled),
            "tolerance": tolerance,
            "zero_arrival_guard_used": total_arrivals <= tolerance,
            "workload_zero_mean_periods_excluded": sum(sum(values) <= tolerance for values in workloads.values()),
        },
        "open_cost": weighted["open"],
        "concentration_raw_used_bays": concentration["raw_used_bays"],
        "concentration_normalized": concentration_normalized,
        "concentration_cost": weighted["concentration"],
        "concentration": concentration,
        "recourse_cost": recourse,
        "core_cost": first_stage + recourse,
        "open_raw": open_raw,
        "distance_raw": distance_raw,
        "balance_raw": balance_raw,
        "conflict_raw": conflict_raw,
        "distance_cost": weighted["distance"],
        "balance_cost": weighted["balance"],
        "conflict_cost": weighted["conflict"],
    }
    return result

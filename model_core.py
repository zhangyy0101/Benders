"""The single complete monolithic core MIP used by every Route-A phase."""
from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from config import Weights
from data import prepare_instance, validate_instance_units
from model_common import (arrival, attribute_score, compute_old_occupancy,
                          group_attr, new_groups, objective_scale_factor,
                          objective_scales, outbound_pressure, raw_components)
from solver_bbc import build_master_v2


def build_core_monolithic_model(data: dict, weights: Weights, *,
        alloc_domain: str = "integer", include_attribute_helpers: bool = False,
        attribute_scope: str = "final", add_valid_inequalities: bool = True):
    if "Bay_Handling_Rate" not in data:
        data = prepare_instance(data)
    validate_instance_units(data)
    if attribute_scope not in {"final", "horizon"}:
        raise ValueError("attribute_scope must be final or horizon")
    model, variables = build_master_v2(data, weights,
        include_attribute_helpers=include_attribute_helpers, alloc_domain=alloc_domain)
    I, J, G, N = data["I_list"], data["J_new"], new_groups(data), data["N"]
    din = model.addVars(J, G, I, N, lb=0.0, name="din")
    inv = model.addVars(J, G, I, N, lb=0.0, name="inv")
    for j in J:
        for g in G:
            for i in I:
                for n in N:
                    initial = float(data["initial_inventory_data"].get((i, j, g), 0.0))
                    previous = inv[j, g, i, n - 1] if n > 0 else initial
                    model.addConstr(inv[j, g, i, n] == previous + din[j, g, i, n], name=f"inventory_{j}_{g}_{i}_{n}")
            for n in N:
                model.addConstr(gp.quicksum(din[j, g, i, n] for i in I) == arrival(data, j, g, n), name=f"arrival_{j}_{g}_{n}")
        for i in I:
            for n in N:
                model.addConstr(float(data["Alpha"]) * gp.quicksum(din[j,g,i,n] for g in G)
                    <= float(data["Bay_Handling_Rate"][(i,n)]) * float(data["Intervals"][n]["dur"]) * variables["x"][i,j,n],
                    name=f"handling_{i}_{j}_{n}")
                for g in G:
                    model.addConstr(float(data["Alpha"]) * inv[j,g,i,n] <= variables["alloc_boxes"][i,j,g,n], name=f"inventory_alloc_{i}_{j}_{g}_{n}")
        for k, bays in data["Bays_in_Block"].items():
            for g in G:
                for n in N:
                    model.addConstr(gp.quicksum(din[j,g,i,n] for i in bays) == variables["in_share"][j,k,g,n], name=f"block_flow_{j}_{k}_{g}_{n}")
    if add_valid_inequalities and not any(float(v) > 1e-9 for v in data.get("New_Outbound_Req", {}).values()):
        for n in N:
            if n == min(N): continue
            for j in J:
                for i in I: model.addConstr(variables["x"][i,j,n] >= variables["x"][i,j,n-1], name=f"monotone_x_{i}_{j}_{n}")
                for k in data["K"]: model.addConstr(variables["block_use_new"][k,j,n] >= variables["block_use_new"][k,j,n-1], name=f"monotone_block_{k}_{j}_{n}")
    for var in variables["block_use_new"].values(): var.BranchPriority = 30
    for var in variables["x"].values(): var.BranchPriority = 20
    for var in variables["alloc_boxes"].values(): var.BranchPriority = 5
    variables.update({"din": din, "inv": inv, "block_use": variables["block_use_new"], "avg": variables["avg_n"]})
    pressure, scales = outbound_pressure(data), objective_scales(data)
    open_raw = gp.quicksum(variables["x"][i,j,n] * float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N)
    distance_raw = gp.quicksum(float(data["Dist"][(j,k)]) * variables["in_share"][j,k,g,n] for j in J for k in data["K"] for g in G for n in N)
    balance_raw = gp.quicksum(variables["g_bal"][k,n] for k in data["K"] for n in N)
    conflict_raw = gp.quicksum(float(pressure[(k,n)]) * variables["in_share"][j,k,g,n] for k in data["K"] for n in N for j in J for g in G)
    core = objective_scale_factor(weights) * (weights.master.x*open_raw/scales["open"] + weights.sub.dist*distance_raw/scales["distance"] + weights.sub.balance*balance_raw/scales["balance"] + weights.sub.conflict*conflict_raw/scales["conflict"])
    pod = gp.quicksum(variables.get("pod_block_use", {}).values())
    weight = gp.quicksum(variables.get("weight_block_use", {}).values())
    height = gp.quicksum(variables.get("bay_height_mix", {}).values())
    attr = objective_scale_factor(weights) * (weights.attribute.pod_spread*pod/scales["pod_spread"] + weights.attribute.weight_spread*weight/scales["weight_spread"] + weights.attribute.height_mix*height/scales["height_mix"])
    model.setObjective(core, GRB.MINIMIZE)
    model.ModelName = "route_a_core_monolithic"
    model.update()
    return model, variables, {"core_objective": core, "open_raw": open_raw, "distance_raw": distance_raw, "balance_raw": balance_raw, "conflict_raw": conflict_raw, "attribute_objective": attr, "pod_raw": pod, "weight_raw": weight, "height_raw": height, "objective_scales": scales, "data": data}


def extract_solution(data, variables):
    return {name: {key: float(var.X) for key, var in values.items()} for name, values in variables.items() if hasattr(values, "items") and values and hasattr(next(iter(values.values())), "X")}


def evaluate_core_solution(data, weights, solution):
    raw = raw_components(data, solution)
    raw["distance"] = sum(float(data["Dist"][(j,k)]) * solution.get("in_share", {}).get((j,k,g,n), 0.0) for j in data["J_new"] for k in data["K"] for g in new_groups(data) for n in data["N"])
    scales = objective_scales(data); factor = objective_scale_factor(weights)
    weighted = {"open": factor*weights.master.x*raw["obj_x"]/scales["open"], "distance": factor*weights.sub.dist*raw["distance"]/scales["distance"], "balance": factor*weights.sub.balance*raw["real_l1"]/scales["balance"], "conflict": factor*weights.sub.conflict*raw["obj_conflict"]/scales["conflict"]}
    return {"raw": raw, "normalized": {"open": raw["obj_x"]/scales["open"], "distance": raw["distance"]/scales["distance"], "balance": raw["real_l1"]/scales["balance"], "conflict": raw["obj_conflict"]/scales["conflict"]}, "weighted": weighted, "total_core_cost": sum(weighted.values()), "attribute_score": attribute_score(data, weights, raw)}

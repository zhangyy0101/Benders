"""The single complete monolithic core MIP used by every Route-A phase."""
from __future__ import annotations

import math
import gurobipy as gp
from gurobipy import GRB

from config import Weights
from data import prepare_instance, validate_instance_units
from model_common import (arrival, attribute_score, attribute_scales, attribute_values, compute_old_occupancy,
                          fixed_in_block, group_attr, group_size, new_groups, objective_scale_factor,
                          objective_scales, outbound_pressure, predecessor_map, raw_components,
                          required_reserve,has_attribute_data)


def build_core_monolithic_model(data: dict, weights: Weights, *,
        alloc_domain: str = "integer", include_attribute_helpers: bool = False,
        attribute_scope: str = "final", attribute_basis: str = "inventory",
        add_valid_inequalities: bool = True, symmetry_breaking: bool = False):
    if "Bay_Handling_Rate" not in data:
        data = prepare_instance(data)
    validate_instance_units(data)
    if attribute_scope not in {"final", "horizon"}:
        raise ValueError("attribute_scope must be final or horizon")
    if attribute_basis not in {"inventory","reservation"}: raise ValueError("invalid attribute basis")
    I, J, G, N = data["I_list"], data["J_new"], new_groups(data), data["N"]
    if alloc_domain not in {"integer","continuous"}: raise ValueError("invalid alloc_domain")
    model=gp.Model("route_a_core_monolithic"); model.Params.OutputFlag=0
    alloc=model.addVars(I,J,G,N,lb=0,vtype=GRB.INTEGER if alloc_domain=="integer" else GRB.CONTINUOUS,name="alloc_boxes")
    x=model.addVars(I,J,N,vtype=GRB.BINARY,name="x"); block=model.addVars(data["K"],J,N,vtype=GRB.BINARY,name="block_use")
    share=model.addVars(J,data["K"],G,N,lb=0,name="in_share"); total=model.addVars(data["K"],N,lb=0,name="in_total"); avg=model.addVars(N,lb=0,name="avg"); bal=model.addVars(data["K"],N,lb=0,name="g_bal")
    old=compute_old_occupancy(data); remaining={(i,n):float(data["I"][i]["cap"])-old.get((i,n),0) for i in I for n in N}; modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I}; pred=predecessor_map(data)
    variables={"alloc_boxes":alloc,"x":x,"block_use":block,"in_share":share,"in_total":total,"avg":avg,"g_bal":bal}
    for i in I:
        for n in N:
            for j in J:
                model.addConstr(gp.quicksum(alloc[i,j,g,n] for g in G)<=remaining[i,n]*x[i,j,n],name=f"alloc_activation_{i}_{j}_{n}")
                model.addConstr(x[i,j,n]<=gp.quicksum(alloc[i,j,g,n] for g in G),name=f"activation_alloc_{i}_{j}_{n}")
                if pred[n] is not None:
                    for g in G: model.addConstr(alloc[i,j,g,n]>=alloc[i,j,g,pred[n]],name=f"monotone_alloc_{i}_{j}_{g}_{n}")
            model.addConstr(gp.quicksum(alloc[i,j,g,n] for j in J for g in G)<=remaining[i,n],name=f"storage_{i}_{n}")
            for g in G:
                if group_size(data,g)!=modes[i]: model.addConstr(gp.quicksum(alloc[i,j,g,n] for j in J)==0,name=f"bay_mode_{i}_{g}_{n}")
    for j in J:
        for k in data["K"]:
            bays=data["Bays_in_Block"][k]
            for n in N:
                model.addConstr(gp.quicksum(x[i,j,n] for i in bays)<=len(bays)*block[k,j,n],name=f"block_forward_{k}_{j}_{n}")
                model.addConstr(block[k,j,n]<=gp.quicksum(x[i,j,n] for i in bays),name=f"block_reverse_{k}_{j}_{n}")
                model.addConstr(gp.quicksum(share[j,k,g,n] for g in G)<=sum(arrival(data,j,g,n) for g in G)*block[k,j,n],name=f"share_block_{j}_{k}_{n}")
        for g in G:
            for n in N:
                model.addConstr(gp.quicksum(share[j,k,g,n] for k in data["K"])==arrival(data,j,g,n),name=f"share_arrival_{j}_{g}_{n}")
                model.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)==required_reserve(data,j,g,n,alloc_domain),name=f"exact_reserve_{j}_{g}_{n}")
    fixed=fixed_in_block(data)
    for k in data["K"]:
        for n in N:
            model.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(share[j,k,g,n] for j in J for g in G),name=f"total_{k}_{n}")
            model.addConstr(bal[k,n]>=total[k,n]-avg[n],name=f"balance_pos_{k}_{n}"); model.addConstr(bal[k,n]>=avg[n]-total[k,n],name=f"balance_neg_{k}_{n}")
    for n in N: model.addConstr(len(data["K"])*avg[n]==gp.quicksum(total[k,n] for k in data["K"]),name=f"average_{n}")
    din = model.addVars(J, G, I, N, lb=0.0, name="din")
    inv = model.addVars(J, G, I, N, lb=0.0, name="inv")
    for j in J:
        for g in G:
            for i in I:
                for n in N:
                    initial = float(data["initial_inventory_data"].get((i, j, g), 0.0))
                    previous = inv[j, g, i, pred[n]] if pred[n] is not None else initial
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
                for i in I: model.addConstr(x[i,j,n] >= x[i,j,pred[n]], name=f"monotone_x_{i}_{j}_{n}")
                for k in data["K"]: model.addConstr(block[k,j,n] >= block[k,j,pred[n]], name=f"monotone_block_{k}_{j}_{n}")
    if add_valid_inequalities:
        alpha=float(data["Alpha"])
        for j in J:
            for size in data["S"]:
                bays=[i for i in I if modes[i]==int(size)]; groups=[g for g in G if group_size(data,g)==int(size)]; cumulative=0.0
                for n in N:
                    period_need=sum(arrival(data,j,g,n) for g in groups); cumulative+=period_need
                    max_work=max([float(data["Bay_Handling_Rate"][(i,n)])*float(data["Intervals"][n]["dur"]) for i in bays]+[0]); max_store=max([remaining[i,n] for i in bays]+[0])
                    if period_need>1e-9 and max_work>1e-9: model.addConstr(gp.quicksum(x[i,j,n] for i in bays)>=math.ceil(alpha*period_need/max_work-1e-9),name=f"minimum_handling_bays_{j}_{size}_{n}")
                    if cumulative>1e-9 and max_store>1e-9: model.addConstr(gp.quicksum(x[i,j,n] for i in bays)>=math.ceil(alpha*cumulative/max_store-1e-9),name=f"minimum_storage_bays_{j}_{size}_{n}")
    pod_use={}; weight_use={}; height_used={}; height_mix={}; periods=[max(N)] if attribute_scope=="final" else list(N)
    if include_attribute_helpers:
        for label,attr,target in (("pod","pod",pod_use),("weight","weight_class",weight_use)):
            values=attribute_values(data,attr); td=model.addVars(J,values,data["K"],periods,vtype=GRB.BINARY,name=f"{label}_block_use")
            target.update(td)
            for j in J:
                for value in values:
                    groups=[g for g in G if group_attr(data,g,attr)==value]
                    for n in periods:
                        total_need=sum(arrival(data,j,g,nn) for g in groups for nn in N if nn<=n)
                        feasible=[]
                        for k in data["K"]:
                            reserve_basis=attribute_basis=="reservation"; cap=sum(remaining[i,n]/float(data["Alpha"]) for i in data["Bays_in_Block"][k] if modes[i] in {group_size(data,g) for g in groups}); feasible.append(cap); demand=total_need if not reserve_basis else float(data["Alpha"])*total_need; basis_cap=cap if not reserve_basis else float(data["Alpha"])*cap; big_m=min(demand,basis_cap)
                            boxes=gp.quicksum((alloc[i,j,g,n] if reserve_basis else inv[j,g,i,n]) for i in data["Bays_in_Block"][k] for g in groups)
                            if big_m>1e-9: model.addConstr(boxes<=big_m*td[j,value,k,n],name=f"{label}_link_{j}_{value}_{k}_{n}")
                            else: model.addConstr(td[j,value,k,n]==0,name=f"{label}_no_capacity_{j}_{value}_{k}_{n}")
                        max_cap=max(feasible,default=0)
                        if total_need>1e-9 and max_cap>1e-9: model.addConstr(gp.quicksum(td[j,value,k,n] for k in data["K"])>=math.ceil(total_need/max_cap-1e-9),name=f"{label}_minimum_blocks_{j}_{value}_{n}")
            for var in td.values(): var.BranchPriority=10
        heights=attribute_values(data,"height"); hu=model.addVars(I,heights,periods,vtype=GRB.BINARY,name="bay_height_used"); hm=model.addVars(I,periods,lb=0,name="bay_height_mix"); height_used.update(hu); height_mix.update(hm)
        for i in I:
            for n in periods:
                for height in heights:
                    reserve_basis=attribute_basis=="reservation"; cap=remaining[i,n] if reserve_basis else remaining[i,n]/float(data["Alpha"]); boxes=gp.quicksum((alloc[i,j,g,n] if reserve_basis else inv[j,g,i,n]) for j in J for g in G if group_attr(data,g,"height")==height); model.addConstr(boxes<=cap*hu[i,height,n],name=f"height_link_{i}_{height}_{n}")
                model.addConstr(hm[i,n]>=gp.quicksum(hu[i,h,n] for h in heights)-1,name=f"height_mix_{i}_{n}")
        for var in hu.values(): var.BranchPriority=10
    variables.update({"pod_block_use":pod_use,"weight_block_use":weight_use,"bay_height_used":height_used,"bay_height_mix":height_mix})
    for var in block.values(): var.BranchPriority = 30
    for var in variables["x"].values(): var.BranchPriority = 20
    for var in variables["alloc_boxes"].values(): var.BranchPriority = 5
    variables.update({"din": din, "inv": inv})
    if symmetry_breaking:
        profiles={}
        for i in I:
            profile=(data["I"][i]["block"],modes[i],tuple(round(remaining[i,n],9) for n in N),tuple(round(float(data["Bay_Handling_Rate"][i,n]),9) for n in N)); profiles.setdefault(profile,[]).append(i)
        for bays in profiles.values():
            for left,right in zip(sorted(bays),sorted(bays)[1:]):
                for n in N: model.addConstr(gp.quicksum(x[left,j,n] for j in J)>=gp.quicksum(x[right,j,n] for j in J),name=f"symmetry_x_{left}_{right}_{n}")
    pressure, scales = outbound_pressure(data), objective_scales(data); attr_scales=attribute_scales(data,attribute_scope)
    open_raw = gp.quicksum(variables["x"][i,j,n] * float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N)
    distance_raw = gp.quicksum(float(data["Dist"][(j,k)]) * variables["in_share"][j,k,g,n] for j in J for k in data["K"] for g in G for n in N)
    balance_raw = gp.quicksum(variables["g_bal"][k,n] for k in data["K"] for n in N)
    conflict_raw = gp.quicksum(float(pressure[(k,n)]) * variables["in_share"][j,k,g,n] for k in data["K"] for n in N for j in J for g in G)
    core = objective_scale_factor(weights) * (weights.master.x*open_raw/scales["open"] + weights.sub.dist*distance_raw/scales["distance"] + weights.sub.balance*balance_raw/scales["balance"] + weights.sub.conflict*conflict_raw/scales["conflict"])
    pod = gp.quicksum(variables.get("pod_block_use", {}).values())
    weight = gp.quicksum(variables.get("weight_block_use", {}).values())
    height = gp.quicksum(variables.get("bay_height_mix", {}).values())
    attr = objective_scale_factor(weights) * (weights.attribute.pod_spread*pod/attr_scales["pod_spread"] + weights.attribute.weight_spread*weight/attr_scales["weight_spread"] + weights.attribute.height_mix*height/attr_scales["height_mix"])
    model.setObjective(core, GRB.MINIMIZE)
    model.ModelName = "route_a_core_monolithic"
    model.update()
    return model, variables, {"core_objective": core, "open_raw": open_raw, "distance_raw": distance_raw, "balance_raw": balance_raw, "conflict_raw": conflict_raw, "attribute_objective": attr, "pod_raw": pod, "weight_raw": weight, "height_raw": height, "objective_scales": scales, "attribute_scales":attr_scales,"symmetry_groups":[v for v in profiles.values() if len(v)>1] if symmetry_breaking else [], "data": data}


def extract_solution(data, variables):
    names=("alloc_boxes","x","block_use","din","inv","in_share","in_total","avg","g_bal")
    return {name:{key:float(var.X) for key,var in variables[name].items()} for name in names}


def evaluate_core_solution(data, weights, solution, attribute_scope="final",attribute_basis="inventory"):
    raw = raw_components(data, solution, attribute_scope=attribute_scope,attribute_basis=attribute_basis)
    raw["distance"] = sum(float(data["Dist"][(j,k)]) * solution.get("in_share", {}).get((j,k,g,n), 0.0) for j in data["J_new"] for k in data["K"] for g in new_groups(data) for n in data["N"])
    scales = objective_scales(data); factor = objective_scale_factor(weights)
    weighted = {"open": factor*weights.master.x*raw["obj_x"]/scales["open"], "distance": factor*weights.sub.dist*raw["distance"]/scales["distance"], "balance": factor*weights.sub.balance*raw["real_l1"]/scales["balance"], "conflict": factor*weights.sub.conflict*raw["obj_conflict"]/scales["conflict"]}
    return {"raw": raw, "normalized": {"open": raw["obj_x"]/scales["open"], "distance": raw["distance"]/scales["distance"], "balance": raw["real_l1"]/scales["balance"], "conflict": raw["obj_conflict"]/scales["conflict"]}, "weighted": weighted, "total_core_cost": sum(weighted.values()), "attribute_score": attribute_score(data, weights, raw,attribute_scope) if has_attribute_data(data) else None}

"""Complete monolithic formulation with an optional sparse candidate domain."""
from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from model_common import (add_common_master_valid_inequalities, arrival, fixed_in_block, group_size,
                          objective_scales, outbound_pressure, remaining_capacity,
                          required_reserve, scale_factor, ship_group_pairs, ship_groups)
from model_concentration import build_joint_group_concentration, concentration_metadata


def _normalize_allowed(data, allowed_group_bays):
    if allowed_group_bays is None:
        return None
    normalized = {}
    for j, g in ship_group_pairs(data):
        bays = tuple(dict.fromkeys(allowed_group_bays.get((j, g), ())))
        unknown = [i for i in bays if i not in data["I_list"]]
        incompatible = [i for i in bays if int(data["Fixed_Bay_Mode"][i]) != group_size(data, g)]
        if unknown or incompatible or not bays:
            raise ValueError(f"invalid restricted bays for {(j, g)}: unknown={unknown}, incompatible={incompatible}, empty={not bays}")
        normalized[j, g] = bays
    return normalized


def _build_monolithic_model(data, weights, *, allowed_group_bays=None, alloc_domain="integer",
                            add_valid_inequalities=True, concentration_enabled=True):
    I, J, N, K = data["I_list"], data["J_new"], data["N"], data["K"]
    pairs = ship_group_pairs(data)
    allowed = _normalize_allowed(data, allowed_group_bays)
    group_bays = {(j, g): tuple(I) if allowed is None else allowed[j, g] for j, g in pairs}
    ship_bays = {j: tuple(i for i in I if any(i in group_bays[j, g] for g in ship_groups(data, j))) for j in J}
    alpha, rem = float(data["Alpha"]), remaining_capacity(data)
    value_type = GRB.INTEGER if alloc_domain == "integer" else GRB.CONTINUOUS
    model = gp.Model("route_b_monolithic" if allowed is None else "route_b_restricted_monolithic")
    model.Params.OutputFlag = 0

    allocation_keys = [(i, j, g, n) for j, g in pairs for i in group_bays[j, g] for n in N]
    x_keys = [(i, j, n) for j in J for i in ship_bays[j] for n in N]
    alloc = model.addVars(allocation_keys, lb=0, vtype=value_type, name="alloc_boxes")
    x = model.addVars(x_keys, vtype=GRB.BINARY, name="x")
    din = model.addVars([(j, g, i, n) for j, g in pairs for i in group_bays[j, g] for n in N], lb=0, name="din")
    inv = model.addVars([(j, g, i, n) for j, g in pairs for i in group_bays[j, g] for n in N], lb=0, name="inv")
    share = model.addVars([(j, k, g, n) for j, g in pairs for k in K for n in N], lb=0, name="in_share")
    total = model.addVars(K, N, lb=0, name="in_total")
    avg = model.addVars(N, lb=0, name="avg")
    bal = model.addVars(K, N, lb=0, name="g_bal")

    for i in I:
        for n in N:
            terms = [alloc[i, j, g, n] for j, g in pairs if i in group_bays[j, g]]
            if terms:
                model.addConstr(gp.quicksum(terms) <= rem[i, n], name=f"bay_capacity_{i}_{n}")
    for j in J:
        for i in ship_bays[j]:
            served = [g for g in ship_groups(data, j) if i in group_bays[j, g]]
            for n in N:
                model.addConstr(gp.quicksum(alloc[i, j, g, n] for g in served) <= rem[i, n] * x[i, j, n], name=f"alloc_x_{i}_{j}_{n}")
                model.addConstr(x[i, j, n] <= gp.quicksum(alloc[i, j, g, n] for g in served), name=f"x_alloc_{i}_{j}_{n}")
                if n > 0:
                    for g in served:
                        model.addConstr(alloc[i, j, g, n] >= alloc[i, j, g, n - 1], name=f"alloc_mono_{i}_{j}_{g}_{n}")
    for j, g in pairs:
        bays = group_bays[j, g]
        for n in N:
            model.addConstr(gp.quicksum(alloc[i, j, g, n] for i in bays) == required_reserve(data, j, g, n, alloc_domain), name=f"exact_reserve_{j}_{g}_{n}")
            model.addConstr(gp.quicksum(din[j, g, i, n] for i in bays) == arrival(data, j, g, n), name=f"arrival_{j}_{g}_{n}")
            for i in bays:
                previous = inv[j, g, i, n - 1] if n > 0 else float(data["initial_inventory_data"].get((i, j, g), 0))
                model.addConstr(inv[j, g, i, n] == previous + din[j, g, i, n], name=f"inventory_{j}_{g}_{i}_{n}")
                model.addConstr(alpha * inv[j, g, i, n] <= alloc[i, j, g, n], name=f"storage_{i}_{j}_{g}_{n}")
                if allowed is None and int(data["Fixed_Bay_Mode"][i]) != group_size(data, g):
                    model.addConstr(alloc[i, j, g, n] == 0, name=f"mode_{i}_{j}_{g}_{n}")
    for j in J:
        for i in ship_bays[j]:
            served = [g for g in ship_groups(data, j) if i in group_bays[j, g]]
            for n in N:
                capacity = float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"])
                model.addConstr(alpha * gp.quicksum(din[j, g, i, n] for g in served) <= capacity * x[i, j, n], name=f"handling_{i}_{j}_{n}")
        for k in K:
            for n in N:
                for g in ship_groups(data, j):
                    bays = [i for i in data["Bays_in_Block"][k] if i in group_bays[j, g]]
                    model.addConstr(share[j, k, g, n] == gp.quicksum(din[j, g, i, n] for i in bays), name=f"share_{j}_{k}_{g}_{n}")
    fixed = fixed_in_block(data)
    for k in K:
        for n in N:
            model.addConstr(total[k, n] == fixed[k, n] + gp.quicksum(share[j, k, g, n] for j, g in pairs), name=f"total_{k}_{n}")
            model.addConstr(bal[k, n] >= total[k, n] - avg[n])
            model.addConstr(bal[k, n] >= avg[n] - total[k, n])
    for n in N:
        model.addConstr(len(K) * avg[n] == gp.quicksum(total[k, n] for k in K))

    variables = {"alloc_boxes": alloc, "x": x, "din": din, "inv": inv, "in_share": share,
                 "in_total": total, "avg": avg, "g_bal": bal}
    add_common_master_valid_inequalities(model, data, variables, enabled=add_valid_inequalities)
    concentration = build_joint_group_concentration(
        model, data, alloc, alloc_domain=alloc_domain,
        enabled=concentration_enabled and weights.master.concentration > 0, x_vars=x,
        allowed_group_bays=allowed,
    )
    if concentration["enabled"]:
        variables["concentration_use"] = concentration["use_vars"]
    scales, pressure = objective_scales(data), outbound_pressure(data)
    open_raw = gp.quicksum(x[i, j, n] * float(data["Intervals"][n]["dur"]) for i, j, n in x.keys())
    open_obj = scale_factor(weights) * weights.master.x * open_raw / scales["open"]
    concentration_obj = scale_factor(weights) * weights.master.concentration * concentration["normalized_expression"]
    dist = gp.quicksum(float(data["Dist"][j, k]) * share[j, k, g, n] for j, g in pairs for k in K for n in N)
    balance = bal.sum()
    conflict = gp.quicksum(float(pressure[k, n]) * share[j, k, g, n] for j, g in pairs for k in K for n in N)
    recourse = scale_factor(weights) * (weights.sub.dist * dist / scales["distance"] + weights.sub.balance * balance / scales["balance"] + weights.sub.conflict * conflict / scales["conflict"])
    core = open_obj + concentration_obj + recourse
    model.setObjective(core, GRB.MINIMIZE)
    model.update()
    full_group_bay_pairs = sum(sum(int(data["Fixed_Bay_Mode"][i]) == group_size(data, g) for i in I) for _j, g in pairs)
    candidate_group_bay_pairs = sum(len(group_bays[pair]) for pair in pairs)
    context = {"core_objective": core, "first_stage_objective": open_obj + concentration_obj,
               "open_objective": open_obj, "concentration_objective": concentration_obj,
               "recourse_objective": recourse, "open_raw": open_raw, "remaining_capacity": rem,
               "concentration_context": concentration, "allowed_group_bays": allowed,
               "candidate_pair_count": candidate_group_bay_pairs, "full_pair_count": full_group_bay_pairs,
               "candidate_pair_ratio": candidate_group_bay_pairs / max(1, full_group_bay_pairs),
               "restricted_variable_count": model.NumVars, "restricted_constraint_count": model.NumConstrs}
    return model, variables, context


def build_monolithic_model(data, weights, *, alloc_domain="integer", add_valid_inequalities=True, concentration_enabled=True):
    return _build_monolithic_model(data, weights, alloc_domain=alloc_domain,
                                   add_valid_inequalities=add_valid_inequalities,
                                   concentration_enabled=concentration_enabled)


def build_restricted_monolithic_model(data, weights, allowed_group_bays, *, alloc_domain="integer",
                                      add_valid_inequalities=True, concentration_enabled=True):
    model, variables, context = _build_monolithic_model(
        data, weights, allowed_group_bays=allowed_group_bays, alloc_domain=alloc_domain,
        add_valid_inequalities=add_valid_inequalities, concentration_enabled=concentration_enabled)
    pair_count, periods = len(ship_group_pairs(data)), len(data["N"])
    bays, ships, blocks = len(data["I_list"]), len(data["J_new"]), len(data["K"])
    concentration_count = 0
    if concentration_enabled and weights.master.concentration > 0:
        meta = concentration_metadata(data, alloc_domain)
        if meta["available"]:
            concentration_count = sum(len(meta["feasible_bays"][pair]) for pair in meta["positive_ship_groups"])
    context["estimated_full_variable_count"] = (
        3 * bays * pair_count * periods + bays * ships * periods + pair_count * blocks * periods
        + 2 * blocks * periods + periods + concentration_count
    )
    return model, variables, context


def extract_solution(vars):
    return {name: {k: float(v.X) for k, v in values.items()} for name, values in vars.items()}


def evaluate_solution(data, weights, solution, *, alloc_domain="integer", concentration_enabled=True):
    from solution_evaluation import evaluate_common_solution
    return evaluate_common_solution(data, weights, solution, alloc_domain=alloc_domain,
                                    concentration_enabled=concentration_enabled)

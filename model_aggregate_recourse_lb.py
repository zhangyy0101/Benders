"""Valid analytic and configurable aggregate lower approximations of global recourse."""
from __future__ import annotations

import time
import gurobipy as gp

from model_common import (arrival, fixed_in_block, group_attr, group_size, groups,
                          objective_scales, outbound_pressure, scale_factor,
                          ship_groups)


def groups_for_ship_pod_size(data, ship, pod, size):
    """Return only active groups matching POD and size; height/weight stay relaxed."""
    return [g for g in ship_groups(data, ship)
            if group_attr(data, g, "pod") == str(pod) and group_size(data, g) == int(size)]


def active_ship_pod_sizes(data):
    triples = []
    for ship in data["J_new"]:
        seen = set()
        for group in ship_groups(data, ship):
            key = (str(group_attr(data, group, "pod")), int(group_size(data, group)))
            if key not in seen:
                triples.append((ship, *key)); seen.add(key)
    return triples


def analytic_recourse_lower_bounds(data, weights):
    G = groups(data); sc = objective_scales(data); factor = scale_factor(weights)
    distance = sum(sum(arrival(data, j, g, n) for g in G if group_size(data, g) == int(s))
                   * min(float(data["Dist"][j, k]) for k in data["K"])
                   for j in data["J_new"] for s in data["S"] for n in data["N"])
    pressure = outbound_pressure(data)
    conflict = sum(sum(arrival(data, j, g, n) for j in data["J_new"] for g in G)
                   * min(float(pressure[k, n]) for k in data["K"]) for n in data["N"])
    model = gp.Model("analytic_balance_lb"); model.Params.OutputFlag = 0
    flow = model.addVars(data["K"], data["N"], lb=0); total = model.addVars(data["K"], data["N"], lb=0)
    avg = model.addVars(data["N"], lb=0); bal = model.addVars(data["K"], data["N"], lb=0); fixed = fixed_in_block(data)
    for n in data["N"]:
        demand = sum(arrival(data, j, g, n) for j in data["J_new"] for g in G)
        model.addConstr(flow.sum('*', n) == demand); model.addConstr(len(data["K"]) * avg[n] == total.sum('*', n))
        for k in data["K"]:
            model.addConstr(total[k, n] == fixed[k, n] + flow[k, n])
            model.addConstr(bal[k, n] >= total[k, n] - avg[n]); model.addConstr(bal[k, n] >= avg[n] - total[k, n])
    model.setObjective(bal.sum()); model.optimize(); balance = float(model.ObjVal)
    weighted = {"distance": factor * weights.sub.dist * distance / sc["distance"],
                "balance": factor * weights.sub.balance * balance / sc["balance"],
                "conflict": factor * weights.sub.conflict * conflict / sc["conflict"]}
    return {**weighted, "total": sum(weighted.values())}


def add_aggregate_recourse_relaxation(model, data, weights, x, alloc, eta, *,
                                      enabled=True, level="size", analytic_enabled=True):
    """Add size or POD-size recourse relaxation.

    Mapping proof: sum any full-recourse bay/group flow over groups with the same
    (ship, block, POD, size, period) to obtain ``z``. Arrival conservation is
    preserved. Summing original storage and handling inequalities gives every
    aggregate constraint below. Distance and conflict are exact under this sum;
    balance is minimized over a relaxation, so the aggregate objective cannot
    exceed the corresponding full-recourse objective.
    """
    started = time.perf_counter()
    if level not in {"size", "pod_size"}:
        raise ValueError(f"unknown aggregate relaxation level {level!r}")
    analytic = analytic_recourse_lower_bounds(data, weights)
    analytic_constr = model.addConstr(eta >= analytic["total"], name="eta_analytic_lb") if analytic_enabled else None
    if not enabled:
        return {"analytic": analytic, "aggregate_objective": None, "variables": {}, "constraint": None,
                "level": level, "variable_count": 0, "constraint_count": int(analytic_constr is not None),
                "build_time": time.perf_counter() - started}
    J, K, S, N = data["J_new"], data["K"], data["S"], data["N"]
    alpha = float(data["Alpha"]); modes = {i: int(data["Fixed_Bay_Mode"][i]) for i in data["I_list"]}
    constraint_count = int(analytic_constr is not None)
    if level == "size":
        z = model.addVars(J, K, S, N, lb=0, name="agg_z")
        def flow(j, k, s, n): return z[j, k, s, n]
        for j in J:
            for s in S:
                gs = [g for g in ship_groups(data, j) if group_size(data, g) == int(s)]
                for n in N:
                    model.addConstr(gp.quicksum(flow(j, k, s, n) for k in K) == sum(arrival(data, j, g, n) for g in gs), name=f"agg_arrival_{j}_{s}_{n}"); constraint_count += 1
                    for k in K:
                        bays = [i for i in data["Bays_in_Block"][k] if modes[i] == int(s)]
                        model.addConstr(alpha * flow(j, k, s, n) <= gp.quicksum(float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"]) * x[i, j, n] for i in bays), name=f"agg_handling_{j}_{k}_{s}_{n}"); constraint_count += 1
                        model.addConstr(alpha * gp.quicksum(flow(j, k, s, t) for t in N if t <= n) <= gp.quicksum(alloc[i, j, g, n] for i in bays for g in gs), name=f"agg_storage_{j}_{k}_{s}_{n}"); constraint_count += 1
    else:
        triples = active_ship_pod_sizes(data)
        z = model.addVars([(j, k, p, s, n) for j, p, s in triples for k in K for n in N], lb=0, name="agg_pod_size_z")
        by_ship_size = {(j, int(s)): [(p, ss) for jj, p, ss in triples if jj == j and int(ss) == int(s)] for j in J for s in S}
        def flow(j, k, s, n): return gp.quicksum(z[j, k, p, ss, n] for p, ss in by_ship_size[j, int(s)])
        for j, pod, size in triples:
            gs = groups_for_ship_pod_size(data, j, pod, size)
            for n in N:
                model.addConstr(gp.quicksum(z[j, k, pod, size, n] for k in K) == sum(arrival(data, j, g, n) for g in gs), name=f"agg_pod_arrival_{j}_{pod}_{size}_{n}"); constraint_count += 1
                for k in K:
                    bays = [i for i in data["Bays_in_Block"][k] if modes[i] == int(size)]
                    model.addConstr(alpha * gp.quicksum(z[j, k, pod, size, t] for t in N if t <= n) <= gp.quicksum(alloc[i, j, g, n] for i in bays for g in gs), name=f"agg_pod_storage_{j}_{k}_{pod}_{size}_{n}"); constraint_count += 1
        for j in J:
            for s in S:
                for n in N:
                    for k in K:
                        bays = [i for i in data["Bays_in_Block"][k] if modes[i] == int(s)]
                        model.addConstr(alpha * flow(j, k, s, n) <= gp.quicksum(float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"]) * x[i, j, n] for i in bays), name=f"agg_pod_handling_{j}_{k}_{s}_{n}"); constraint_count += 1
    for j in J:
        for k in K:
            for n in N:
                model.addConstr(alpha * gp.quicksum(flow(j, k, s, n) for s in S) <= gp.quicksum(float(data["Bay_Handling_Rate"][i, n]) * float(data["Intervals"][n]["dur"]) * x[i, j, n] for i in data["Bays_in_Block"][k]), name=f"agg_total_handling_{j}_{k}_{n}"); constraint_count += 1
    total = model.addVars(K, N, lb=0, name="agg_total"); avg = model.addVars(N, lb=0, name="agg_avg"); bal = model.addVars(K, N, lb=0, name="agg_bal")
    fixed = fixed_in_block(data); pressure = outbound_pressure(data)
    for k in K:
        for n in N:
            model.addConstr(total[k, n] == fixed[k, n] + gp.quicksum(flow(j, k, s, n) for j in J for s in S)); constraint_count += 1
            model.addConstr(bal[k, n] >= total[k, n] - avg[n]); model.addConstr(bal[k, n] >= avg[n] - total[k, n]); constraint_count += 2
    for n in N:
        model.addConstr(len(K) * avg[n] == gp.quicksum(total[k, n] for k in K)); constraint_count += 1
    sc = objective_scales(data); factor = scale_factor(weights)
    distance = factor * weights.sub.dist * gp.quicksum(float(data["Dist"][j, k]) * flow(j, k, s, n) for j in J for k in K for s in S for n in N) / sc["distance"]
    balance = factor * weights.sub.balance * gp.quicksum(bal[k, n] for k in K for n in N) / sc["balance"]
    conflict = factor * weights.sub.conflict * gp.quicksum(float(pressure[k, n]) * flow(j, k, s, n) for j in J for k in K for s in S for n in N) / sc["conflict"]
    objective = distance + balance + conflict
    constraint = model.addConstr(eta >= objective, name=f"eta_aggregate_{level}_lb"); constraint_count += 1
    variables = {"z": z, "total": total, "avg": avg, "bal": bal}
    return {"analytic": analytic, "aggregate_objective": objective, "distance": distance, "balance": balance,
            "conflict": conflict, "variables": variables, "constraint": constraint, "level": level,
            "variable_count": sum(len(value) for value in variables.values()), "constraint_count": constraint_count,
            "build_time": time.perf_counter() - started}

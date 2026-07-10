"""Plain monolithic Gurobi baseline using the Route-A core builder."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime

import gurobipy as gp
from gurobipy import GRB

from config import Weights
from model_core import build_core_monolithic_model, evaluate_core_solution, extract_solution
from data import (
    prepare_instance,
    get_data_baptbi_10n_4b_4p,
    get_data_baptbi_15n_4b_5p,
    get_data_baptbi_25n_6b_5p,
    get_data_baptbi_5n_4b_4p,
    get_data_baptbi_8n_4b_4p,
    get_data_barcelona_bcn36a_5n,
    get_data_barcelona_bcn36a_8n,
    get_data_barcelona_bcn36a_10n,
    get_data_barcelona_bcn36a_20n,
    get_data_3new6old_fixed,
)
from solver_bbc import (
    build_master_v2,
    _arrival,
    _compute_old_occupancy,
    _master_raw_components_from_fix,
    _new_groups,
    _objective_scales,
    _objective_scale_factor,
    _outbound_pressure,
    _weighted_master_cost,
)


INSTANCES = {
    "3new6old": get_data_3new6old_fixed,
    "baptbi_5n_4b_4p": get_data_baptbi_5n_4b_4p,
    "baptbi_8n_4b_4p": get_data_baptbi_8n_4b_4p,
    "baptbi_10n_4b_4p": get_data_baptbi_10n_4b_4p,
    "baptbi_15n_4b_5p": get_data_baptbi_15n_4b_5p,
    "baptbi_25n_6b_5p": get_data_baptbi_25n_6b_5p,
    "barcelona_bcn36a_5n": get_data_barcelona_bcn36a_5n,
    "barcelona_bcn36a_8n": get_data_barcelona_bcn36a_8n,
    "barcelona_bcn36a_10n": get_data_barcelona_bcn36a_10n,
    "barcelona_bcn36a_20n": get_data_barcelona_bcn36a_20n,
}


def add_per_ship_feasibility_to_master(model: gp.Model, data: dict, mp_vars: dict) -> dict:
    """
    Add the SP_j variables and constraints to the lifted master.

    These constraints are the monolithic version of build_and_solve_sp_per_ship_lp:
    they link bay-level din/inv to x, alloc_boxes, and in_share as variables
    instead of fixing those values and separating feasibility cuts.
    """
    K = data["K"]
    I = data["I"]
    I_list = data["I_list"]
    Bays_in_Block = data["Bays_in_Block"]
    J_new = data["J_new"]
    G = _new_groups(data)
    N = data["N"]
    Alpha = float(data["Alpha"])
    Intervals = data["Intervals"]
    initial_inventory_data = data["initial_inventory_data"]
    old_occupancy = _compute_old_occupancy(data)

    x = mp_vars["x"]
    alloc_boxes = mp_vars["alloc_boxes"]
    in_share = mp_vars["in_share"]

    din = model.addVars(J_new, G, I_list, N, lb=0.0, name="direct_din")
    inv = model.addVars(J_new, G, I_list, N, lb=0.0, name="direct_inv")

    for j in J_new:
        for s in G:
            for i in I_list:
                init_inv = float(initial_inventory_data.get((i, j, s), 0.0))
                for n in N:
                    prev = inv[j, s, i, n - 1] if n > 0 else init_inv
                    model.addConstr(
                        inv[j, s, i, n] == prev + din[j, s, i, n],
                        name=f"direct_bal_{j}_{s}_{i}_{n}",
                    )

    for j in J_new:
        for s in G:
            for n in N:
                model.addConstr(
                    gp.quicksum(din[j, s, i, n] for i in I_list)
                    == _arrival(data, j, s, n),
                    name=f"direct_arr_{j}_{s}_{n}",
                )

    for j in J_new:
        for i in I_list:
            for s in G:
                for n in N:
                    model.addConstr(
                        Alpha * inv[j, s, i, n] <= alloc_boxes[i, j, s, n],
                        name=f"direct_link_box_cap_{i}_{j}_{s}_{n}",
                    )

    for j in J_new:
        for i in I_list:
            for n in N:
                dur = float(Intervals[n]["dur"])
                model.addConstr(
                    Alpha * gp.quicksum(din[j, s, i, n] for s in G)
                    <= float(data["Bay_Handling_Rate"][(i, n)]) * dur * x[i, j, n],
                    name=f"direct_link_work_{i}_{j}_{n}",
                )

    for j in J_new:
        for k in K:
            bays = Bays_in_Block[k]
            for s in G:
                for n in N:
                    model.addConstr(
                        gp.quicksum(din[j, s, i, n] for i in bays)
                        == in_share[j, k, s, n],
                        name=f"direct_link_in_share_{j}_{k}_{s}_{n}",
                    )

    return {"din": din, "inv": inv}


def set_direct_objective(
    model: gp.Model,
    data: dict,
    weights: Weights,
    mp_vars: dict,
) -> None:
    """Set the monolithic objective with exact L1 block-flow balance."""
    K = data["K"]
    I_list = data["I_list"]
    J_new = data["J_new"]
    G = _new_groups(data)
    N = data["N"]
    Intervals = data["Intervals"]
    Dist = data["Dist"]
    pressure = _outbound_pressure(data)
    scales = _objective_scales(data)

    x = mp_vars["x"]
    in_share = mp_vars["in_share"]
    g_bal = mp_vars["g_bal"]

    obj_x = gp.quicksum(
        x[i, j, n] * float(Intervals[n]["dur"])
        for i in I_list for j in J_new for n in N
    )
    obj_conflict = gp.quicksum(
        float(pressure[(k, n)]) * gp.quicksum(in_share[j, k, g, n] for j in J_new for g in G)
        for k in K for n in N
        if float(pressure[(k, n)]) > 1e-9
    )
    obj_distance = gp.quicksum(
        float(Dist[(j, k)]) * in_share[j, k, g, n]
        for j in J_new for k in K for g in G for n in N
    )
    obj_balance = gp.quicksum(g_bal[k, n] for k in K for n in N)

    obj_expr = (
        weights.master.x * obj_x / scales["open"]
        + weights.sub.balance * obj_balance / scales["balance"]
        + weights.sub.conflict * obj_conflict / scales["conflict"]
        + weights.sub.dist * obj_distance / scales["distance"]
    )
    model.setObjective(_objective_scale_factor(weights) * obj_expr, GRB.MINIMIZE)


def build_direct_model(
    data: dict,
    weights: Weights,
    *, alloc_domain="integer", add_valid_inequalities=True,
) -> tuple[gp.Model, dict]:
    model, variables, expressions = build_core_monolithic_model(data, weights, alloc_domain=alloc_domain, add_valid_inequalities=add_valid_inequalities)
    model.ModelName = "plain_monolithic_gurobi_baseline"
    return model, variables


def evaluate_solution(data: dict, weights: Weights, model: gp.Model, vars_: dict) -> dict:
    """Compute true objective components from a solved direct model."""
    K = data["K"]
    I_list = data["I_list"]
    J_new = data["J_new"]
    G = _new_groups(data)
    N = data["N"]
    Intervals = data["Intervals"]
    Dist = data["Dist"]

    obj_x = sum(
        float(vars_["x"][i, j, n].X) * float(Intervals[n]["dur"])
        for i in I_list for j in J_new for n in N
    )
    obj_distance = sum(
        float(Dist[(j, k)]) * float(vars_["in_share"][j, k, g, n].X)
        for j in J_new for k in K for g in G for n in N
    )
    in_total_v = {
        (k, n): float(vars_["in_total"][k, n].X)
        for k in K for n in N
    }
    mp_fix = {
        "x": {(i, j, n): float(vars_["x"][i, j, n].X) for i in I_list for j in J_new for n in N},
        "alloc_boxes": {
            (i, j, g, n): float(vars_["alloc_boxes"][i, j, g, n].X)
            for i in I_list for j in J_new for g in G for n in N
        },
        "in_share": {
            (j, k, g, n): float(vars_["in_share"][j, k, g, n].X)
            for j in J_new for k in K for g in G for n in N
        },
    }
    raw = _master_raw_components_from_fix(data, mp_fix, in_total_v=in_total_v)
    scales = _objective_scales(data)
    obj_scale = _objective_scale_factor(weights)
    weighted_distance = obj_scale * weights.sub.dist * obj_distance / scales["distance"]
    true_obj = _weighted_master_cost(data, weights, raw) + weighted_distance
    return {
        "true_obj": true_obj,
        "obj_x_raw": obj_x,
        "obj_balance_raw": raw["real_l1"],
        "obj_conflict_raw": raw["obj_conflict"],
        "obj_distance_raw": obj_distance,
        "obj_pod_spread_raw": raw.get("pod_spread", 0.0),
        "obj_weight_spread_raw": raw.get("weight_spread", 0.0),
        "obj_height_mix_raw": raw.get("height_mix", 0.0),
        "weighted_x": obj_scale * weights.master.x * obj_x / scales["open"],
        "weighted_balance": obj_scale * weights.sub.balance * raw["real_l1"] / scales["balance"],
        "weighted_conflict": obj_scale * weights.sub.conflict * raw["obj_conflict"] / scales["conflict"],
        "weighted_distance": weighted_distance,
    }


def _gap(ub, lb):
    if ub is None or lb is None:
        return None
    if abs(float(ub)) <= 1e-9:
        return None
    return (float(ub) - float(lb)) / abs(float(ub))


def solve_direct_gurobi(
    data: dict,
    weights: Weights,
    *,
    time_limit_s: float | None = None,
    mip_gap: float = 0.05,
    threads: int | None = None,
    method: int | None = None,
    node_method: int | None = None,
    mip_focus: int | None = None,
    heuristics: float | None = None,
    no_rel_heur_time: float | None = None,
    cuts: int | None = None,
    presolve: int | None = None,
    verbose: bool = True,
    alloc_domain: str = "integer",
    add_valid_inequalities: bool = True,
    start_solution: dict | None = None,
) -> dict:
    model, vars_ = build_direct_model(data, weights, alloc_domain=alloc_domain, add_valid_inequalities=add_valid_inequalities)
    if start_solution:
        for name, values in start_solution.items():
            for key, value in values.items():
                if key in vars_.get(name, {}): vars_[name][key].Start = value
    model.Params.OutputFlag = 1 if verbose else 0
    model.Params.MIPGap = float(mip_gap)
    if time_limit_s is not None:
        model.Params.TimeLimit = float(time_limit_s)
    if threads is not None:
        model.Params.Threads = int(threads)
    if method is not None:
        model.Params.Method = int(method)
    if node_method is not None:
        model.Params.NodeMethod = int(node_method)
    if mip_focus is not None:
        model.Params.MIPFocus = int(mip_focus)
    if heuristics is not None:
        model.Params.Heuristics = float(heuristics)
    if no_rel_heur_time is not None:
        model.Params.NoRelHeurTime = float(no_rel_heur_time)
    if cuts is not None:
        model.Params.Cuts = int(cuts)
    if presolve is not None:
        model.Params.Presolve = int(presolve)
    t0 = time.perf_counter()
    model.optimize()
    wall = time.perf_counter() - t0

    has_sol = model.SolCount > 0
    solution = extract_solution(data, vars_) if has_sol else None
    core_eval = evaluate_core_solution(data, weights, solution) if has_sol else None
    components = None if core_eval is None else {"true_obj":core_eval["total_core_cost"], **core_eval["weighted"]}
    obj_val = float(model.ObjVal) if has_sol else None
    obj_bound = None
    if model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED, GRB.SUBOPTIMAL):
        try:
            obj_bound = float(model.ObjBound)
        except Exception:
            obj_bound = None

    true_ub = core_eval["total_core_cost"] if core_eval else None
    true_lb = obj_bound
    true_gap = _gap(true_ub, true_lb)

    return {
        "ok": has_sol,
        "status": int(model.Status),
        "status_name": _status_name(model.Status),
        "objective_mode": "exact_l1_balance_mip",
        "model_obj": obj_val,
        "model_bound": obj_bound,
        "model_gap": float(model.MIPGap) if has_sol and hasattr(model, "MIPGap") else None,
        "true_obj": true_ub,
        "true_bound": true_lb,
        "true_gap": true_gap,
        "true_bound_source": "exact_l1_mip_bound",
        "components": components,
        "wall_time_s": wall,
        "node_count": float(model.NodeCount),
        "sol_count": int(model.SolCount),
        "num_vars": int(model.NumVars),
        "num_constrs": int(model.NumConstrs),
        "num_qconstrs": int(model.NumQConstrs),
    }


def _status_name(status: int) -> str:
    names = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.SUBOPTIMAL: "SUBOPTIMAL",
    }
    return names.get(status, str(status))


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct monolithic Gurobi runner")
    parser.add_argument("--instance", choices=INSTANCES.keys(), default="3new6old")
    parser.add_argument("--time", type=float, default=None,
                        help="Gurobi time limit in seconds")
    parser.add_argument("--mip-gap", type=float, default=0.05,
                        help="relative MIP gap target (default: 0.05)")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--method", type=int, default=None,
                        help="Gurobi Method parameter, e.g. 2 for barrier")
    parser.add_argument("--node-method", type=int, default=None,
                        help="Gurobi NodeMethod parameter")
    parser.add_argument("--mip-focus", type=int, default=None,
                        help="Gurobi MIPFocus parameter")
    parser.add_argument("--heuristics", type=float, default=None,
                        help="Gurobi Heuristics parameter")
    parser.add_argument("--no-rel-heur-time", type=float, default=None,
                        help="Gurobi NoRelHeurTime parameter in seconds")
    parser.add_argument("--cuts", type=int, default=None,
                        help="Gurobi Cuts parameter")
    parser.add_argument("--presolve", type=int, default=None,
                        help="Gurobi Presolve parameter")
    parser.add_argument("--output-root", default="outputs")
    parser.add_argument("--alloc-domain", choices=("integer", "continuous"), default="integer")
    parser.add_argument("--handling-rate-scale", type=float, default=1.0)
    parser.add_argument("--no-valid-inequalities", action="store_true")
    parser.add_argument("--start-solution", help="JSON solution file (reserved for tuple-key compatible exports)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    data = prepare_instance(INSTANCES[args.instance](), args.handling_rate_scale)
    weights = Weights()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.abspath(os.path.join(args.output_root, f"direct_run_{run_id}_{args.instance}"))
    os.makedirs(out_dir, exist_ok=True)

    print(f"[direct] instance       = {args.instance}")
    print("[direct] objective mode = exact L1 balance MIP")
    print(f"[direct] time limit     = {args.time if args.time is not None else 'none'}")
    print(f"[direct] output dir     = {out_dir}")

    result = solve_direct_gurobi(
        data,
        weights,
        time_limit_s=args.time,
        mip_gap=args.mip_gap,
        threads=args.threads,
        method=args.method,
        node_method=args.node_method,
        mip_focus=args.mip_focus,
        heuristics=args.heuristics,
        no_rel_heur_time=args.no_rel_heur_time,
        cuts=args.cuts,
        presolve=args.presolve,
        verbose=not args.quiet,
        alloc_domain=args.alloc_domain,
        add_valid_inequalities=not args.no_valid_inequalities,
    )
    result["instance"] = args.instance

    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    print()
    print("=" * 70)
    print(f"Direct Gurobi status: {result['status_name']}")
    if result["ok"]:
        print("  Exact L1 objective metrics:")
        print(f"    UB={result['model_obj']:.2f}")
        if result["model_bound"] is not None:
            print(f"    LB={result['model_bound']:.2f}")
        if result["model_gap"] is not None:
            print(f"    gap={100.0 * result['model_gap']:.2f}%")
        c = result["components"]
        print(f"  Components:      open={c['open']:.2f}, dist={c['distance']:.2f}, "
              f"balance={c['balance']:.2f}, conflict={c['conflict']:.2f}")
    print(f"  Wall time:       {result['wall_time_s']:.2f}s")
    print(f"  Summary saved:   {summary_path}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

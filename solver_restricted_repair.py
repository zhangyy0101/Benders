"""Solve and independently verify a restricted monolithic repair MIP."""
from __future__ import annotations

import time

from gurobipy import GRB

from model_common import first_stage_cost
from model_monolithic import build_restricted_monolithic_model, extract_solution
from model_recourse import GlobalRecourseOracle
from solution_evaluation import evaluate_common_solution
from solution_validation import validate_solution


def _status_name(status):
    return {GRB.OPTIMAL: "OPTIMAL", GRB.TIME_LIMIT: "TIME_LIMIT", GRB.INFEASIBLE: "INFEASIBLE",
            GRB.INF_OR_UNBD: "INF_OR_UNBD", GRB.INTERRUPTED: "INTERRUPTED",
            GRB.SUBOPTIMAL: "SUBOPTIMAL", GRB.SOLUTION_LIMIT: "SOLUTION_LIMIT"}.get(status, str(status))


def solve_restricted_monolithic_repair(data, weights, allowed_group_bays, *, time_limit: float,
                                       guide_result=None, threads: int = 1, seed: int = 0,
                                       mip_gap: float = .03, alloc_domain: str = "integer",
                                       add_valid_inequalities: bool = True,
                                       concentration_enabled: bool = True,
                                       solution_limit: int | None = None,
                                       validation_time_reserve: float = 0.0,
                                       canonical_oracle: bool = True) -> dict:
    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit))
    build_started = time.perf_counter()
    model, variables, context = build_restricted_monolithic_model(
        data, weights, allowed_group_bays, alloc_domain=alloc_domain,
        add_valid_inequalities=add_valid_inequalities, concentration_enabled=concentration_enabled)
    build_runtime = time.perf_counter() - build_started
    try:
        guide = guide_result or {}
        for name, values in variables.items():
            supplied = guide.get(name, {})
            for key, var in values.items():
                if key in supplied:
                    var.Start = float(supplied[key])
        remaining = max(0.0, deadline - time.perf_counter())
        model.Params.OutputFlag = 0
        model.Params.Threads = int(threads or 1)
        model.Params.Seed = int(seed)
        model.Params.MIPGap = float(mip_gap)
        model.Params.MIPFocus = 1
        model.Params.Heuristics = .5
        if solution_limit is not None:
            model.Params.SolutionLimit = max(1, int(solution_limit))
        model.Params.TimeLimit = max(0.0, remaining - max(0.0, float(validation_time_reserve)))
        optimize_started = time.perf_counter()
        first_incumbent_time = [None]
        def incumbent_callback(_model, where):
            if where == GRB.Callback.MIPSOL and first_incumbent_time[0] is None:
                first_incumbent_time[0] = time.perf_counter() - started
        if model.Params.TimeLimit > 0:
            model.optimize(incumbent_callback)
        optimization_runtime = time.perf_counter() - optimize_started
        base = {"ok": False, "status_name": "DEADLINE_EXHAUSTED" if remaining <= 0 else _status_name(model.Status),
                "runtime": time.perf_counter() - started, "model_build_runtime": build_runtime,
                "optimization_runtime": optimization_runtime, "solution": None, "canonical_ub": None,
                "repair_objective": None, "guide_start_used": bool(guide_result),
                "time_to_first_repair_incumbent": first_incumbent_time[0],
                **{key: context[key] for key in ("candidate_pair_count", "full_pair_count", "candidate_pair_ratio",
                                                  "restricted_variable_count", "estimated_full_variable_count",
                                                  "restricted_constraint_count")}}
        if remaining <= 0 or model.SolCount == 0:
            return base
        sparse_solution = extract_solution(variables)
        checker = validate_solution(data, sparse_solution, alloc_domain=alloc_domain,
                                    add_valid_inequalities=add_valid_inequalities,
                                    concentration_enabled=concentration_enabled)
        if not checker["feasible"]:
            raise RuntimeError(f"restricted repair incumbent failed checker: {checker}")
        evaluation = evaluate_common_solution(data, weights, sparse_solution, alloc_domain=alloc_domain,
                                              concentration_enabled=concentration_enabled)
        repair_objective = float(model.ObjVal)
        if abs(repair_objective - evaluation["core_cost"]) > 1e-5:
            raise AssertionError("restricted repair objective differs from common evaluator")
        if not canonical_oracle:
            return {**base, "ok": True, "status_name": _status_name(model.Status),
                    "runtime": time.perf_counter() - started, "repair_objective": repair_objective,
                    "canonical_ub": repair_objective, "solution": sparse_solution,
                    "sparse_repair_solution": sparse_solution, "checker": checker,
                    "canonical_checker": checker, "evaluation": evaluation,
                    "oracle_status_name": "NOT_REQUESTED",
                    "ub_source": "checked_monolithic_feasible_solution"}
        oracle = GlobalRecourseOracle(data, weights)
        try:
            oracle.update_rhs(sparse_solution["x"], sparse_solution["alloc_boxes"])
            oracle.model.Params.TimeLimit = max(0.0, deadline - time.perf_counter())
            oracle_status = oracle.solve()
            if oracle_status != GRB.OPTIMAL:
                return {**base, "ok": True, "status_name": f"FEASIBLE_ORACLE_{_status_name(oracle_status)}",
                        "runtime": time.perf_counter() - started, "repair_objective": repair_objective,
                        "canonical_ub": repair_objective, "solution": sparse_solution,
                        "sparse_repair_solution": sparse_solution, "checker": checker,
                        "canonical_checker": checker, "evaluation": evaluation,
                        "oracle_status_name": _status_name(oracle_status),
                        "ub_source": "checked_monolithic_feasible_solution"}
            first = first_stage_cost(data, weights, sparse_solution["x"], sparse_solution["alloc_boxes"],
                                     alloc_domain=alloc_domain, concentration_enabled=concentration_enabled)
            oracle_recourse = oracle.objective_value()
            canonical_ub = first["total"] + oracle_recourse
            if canonical_ub > repair_objective + 1e-5:
                raise AssertionError("oracle canonical UB exceeds repair objective")
            canonical_solution = {"x": sparse_solution["x"], "alloc_boxes": sparse_solution["alloc_boxes"],
                                  **oracle.solution()}
            if "concentration_use" in sparse_solution:
                canonical_solution["concentration_use"] = sparse_solution["concentration_use"]
            canonical_checker = validate_solution(data, canonical_solution, alloc_domain=alloc_domain,
                                                  add_valid_inequalities=add_valid_inequalities,
                                                  concentration_enabled=concentration_enabled)
            if not canonical_checker["feasible"]:
                raise RuntimeError(f"canonical oracle solution failed checker: {canonical_checker}")
        finally:
            oracle.model.dispose()
        return {**base, "ok": True, "runtime": time.perf_counter() - started,
                "repair_objective": repair_objective, "canonical_ub": canonical_ub,
                "solution": canonical_solution, "sparse_repair_solution": sparse_solution,
                "checker": checker, "canonical_checker": canonical_checker,
                "evaluation": evaluation, "oracle_status_name": _status_name(oracle_status),
                "oracle_recourse": oracle_recourse}
    finally:
        model.dispose()

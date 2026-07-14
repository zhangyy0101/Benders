"""Deadline-aware standalone Aggregate-Guided Fix-and-Repair solver."""
from __future__ import annotations

import time

from candidate_domain import build_candidate_domain, check_joint_candidate_feasibility
from model_common import group_size, ship_groups
from solver_aggregate_guide import solve_aggregate_guide
from solver_restricted_repair import solve_restricted_monolithic_repair


def solve_aggregate_guided_fix_and_repair(
    data,
    weights,
    *,
    time_limit: float,
    threads: int = 1,
    seed: int = 0,
    mip_gap: float = .05,
    alloc_domain: str = "integer",
    concentration_enabled: bool = True,
    guide_time_share: float = .25,
    max_expansions: int = 2,
    candidate_options: dict | None = None,
) -> dict:
    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit))
    trace, attempts = [], []
    domains = []

    def remaining():
        return max(0.0, deadline - time.perf_counter())

    guide_cap = min(max(0.0, float(time_limit) * float(guide_time_share)), remaining())
    guide = solve_aggregate_guide(data, weights, time_limit=guide_cap, threads=threads, seed=seed,
                                  alloc_domain=alloc_domain, concentration_enabled=concentration_enabled)
    trace.append({"time": time.perf_counter() - started, "phase": "guide", "source": guide["source"],
                  "ub": None, "lb": None})
    options = dict(candidate_options or {})
    options.pop("expansion_level", None)
    options["auto_expand_joint"] = False
    options.setdefault("joint_time_limit", .75)
    max_compatible = max((sum(int(data["Fixed_Bay_Mode"][i]) == group_size(data, g) for i in data["I_list"])
                          for j in data["J_new"] for g in ship_groups(data, j)), default=0)
    if max_compatible <= 3:
        options.setdefault("min_bays_per_group", 1)
    domain_guide = guide
    if guide["source"] == "static_fallback" and remaining() > 0:
        full_compatible = {(j, g): [i for i in data["I_list"] if int(data["Fixed_Bay_Mode"][i]) == group_size(data, g)]
                           for j in data["J_new"] for g in ship_groups(data, j)}
        coverage_guide = check_joint_candidate_feasibility(
            data, full_compatible, time_limit=min(4.0, remaining()), threads=threads)
        if coverage_guide["status"] == "feasible" and coverage_guide.get("reserve_support"):
            domain_guide = {**guide, "diagnostics": {**guide.get("diagnostics", {}),
                            "alloc_support_by_ship_group_bay": coverage_guide["reserve_support"]}}
    selected = None
    last_status = "no_repair_incumbent"
    previous_solution = None
    first_level = 0
    for attempt_index in range(max(0, int(max_expansions)) + 1):
        if remaining() <= 0:
            last_status = "deadline_exhausted_before_repair"
            break
        level = min(2, first_level + attempt_index)
        options["joint_time_limit"] = min(float(options.get("joint_time_limit", 2.0)), remaining())
        domain = build_candidate_domain(data, domain_guide, expansion_level=level, **options)
        if level == 2 and domain["diagnostics"]["joint_coverage_status"] == "infeasible":
            rankings = domain["scores"]["bay_rankings"]
            bays = domain["candidate_bays"]
            breadth_rounds = 0
            while domain["diagnostics"]["joint_coverage_status"] == "infeasible" and remaining() > 0:
                changed = False
                for key, ranking in rankings.items():
                    additions = [i for i in ranking if i not in bays[key]][:11]
                    if additions:
                        bays[key].extend(additions); changed = True
                if not changed or all(len(bays[key]) == len(ranking) for key, ranking in rankings.items()):
                    break
                breadth_rounds += 1
                joint = check_joint_candidate_feasibility(data, bays, time_limit=min(options["joint_time_limit"], remaining()), threads=threads)
                domain["coverage"]["joint"] = joint
                domain["diagnostics"]["joint_coverage_status"] = joint["status"]
            candidate_count = sum(len(value) for value in bays.values())
            full_count = domain["diagnostics"]["full_group_bay_pair_count"]
            domain["candidate_ship_bays"] = {(i, j) for (j, _g), values in bays.items() for i in values}
            domain["diagnostics"].update({"candidate_group_bay_pair_count": candidate_count,
                                           "candidate_pair_ratio": candidate_count / max(1, full_count),
                                           "candidate_ship_bay_pair_count": len(domain["candidate_ship_bays"]),
                                           "standalone_breadth_expansion_rounds": breadth_rounds})
        domains.append(domain)
        coverage = domain["diagnostics"]["joint_coverage_status"]
        if coverage == "infeasible":
            attempts.append({"attempt": attempt_index, "expansion_level": level, "coverage_status": coverage,
                             "status_name": "coverage_infeasible", "ok": False,
                             "candidate_pair_ratio": domain["diagnostics"]["candidate_pair_ratio"]})
            last_status = "coverage_infeasible"
            continue
        if remaining() <= 0:
            last_status = "deadline_exhausted_before_repair"
            attempts.append({"attempt": attempt_index, "expansion_level": level, "coverage_status": coverage,
                             "status_name": last_status, "ok": False,
                             "candidate_pair_ratio": domain["diagnostics"]["candidate_pair_ratio"]})
            break
        coverage_start = domain["coverage"]["joint"].get("partial_start") or {}
        completed_start = None
        if coverage != "infeasible" and remaining() > 0:
            completion = check_joint_candidate_feasibility(
                data, domain["candidate_bays"], time_limit=min(4.0, remaining()), threads=threads,
                integer_reserve=True)
            completed_start = completion.get("full_start")
            if completion["status"] == "infeasible":
                attempts.append({"attempt": attempt_index, "expansion_level": level,
                                 "coverage_status": "integer_infeasible",
                                 "status_name": "integer_coverage_infeasible", "ok": False,
                                 "candidate_pair_ratio": domain["diagnostics"]["candidate_pair_ratio"]})
                last_status = "integer_coverage_infeasible"
                continue
        if previous_solution is None:
            start = completed_start or {"x": {**guide.get("x", {}), **coverage_start.get("x", {})},
                                        "alloc_boxes": dict(guide.get("alloc_boxes", {}))}
        else:
            start = {"x": previous_solution.get("x", {}), "alloc_boxes": previous_solution.get("alloc_boxes", {})}
        repair = solve_restricted_monolithic_repair(
            data, weights, domain["candidate_bays"], time_limit=remaining(), guide_result=start,
            threads=threads, seed=seed + attempt_index, mip_gap=mip_gap, alloc_domain=alloc_domain,
            add_valid_inequalities=True, concentration_enabled=concentration_enabled, solution_limit=1,
            validation_time_reserve=min(2.5, .15 * max(0.0, float(time_limit))))
        attempt = {"attempt": attempt_index, "expansion_level": level, "coverage_status": coverage,
                   "candidate_pair_ratio": domain["diagnostics"]["candidate_pair_ratio"], **repair}
        attempts.append(attempt)
        last_status = repair["status_name"]
        if repair["ok"]:
            previous_solution = repair["sparse_repair_solution"]
            incumbent_time = repair.get("time_to_first_repair_incumbent")
            if incumbent_time is not None:
                trace.append({"time": min(time.perf_counter() - started, trace[-1]["time"] + incumbent_time),
                              "phase": "repair", "source": "restricted_monolithic_incumbent",
                              "ub": repair["repair_objective"], "lb": None})
            trace.append({"time": time.perf_counter() - started, "phase": "repair",
                          "source": "oracle_canonical_ub", "ub": repair["canonical_ub"], "lb": None})
            selected = attempt_index
            break

    runtime = time.perf_counter() - started
    if selected is None:
        return {"ok": False, "status_name": last_status, "runtime": runtime, "ub": None,
                "solution": None, "evaluation": None, "guide": guide,
                "candidate_domain": domains[-1] if domains else None, "repair_attempts": attempts,
                "selected_attempt": None, "oracle_consistent": None, "anytime_trace": trace}
    best = attempts[selected]
    trace.append({"time": runtime, "phase": "final", "source": "selected_final_ub",
                  "ub": best["canonical_ub"], "lb": None})
    return {"ok": True, "status_name": best["status_name"], "runtime": runtime,
            "ub": best["canonical_ub"], "solution": best["solution"], "evaluation": best["evaluation"],
            "guide": guide, "candidate_domain": domains[selected], "repair_attempts": attempts,
            "selected_attempt": selected, "oracle_consistent": best["canonical_ub"] <= best["repair_objective"] + 1e-5,
            "anytime_trace": trace}

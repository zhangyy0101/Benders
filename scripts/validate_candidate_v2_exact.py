"""P6A exact gate for candidate-v1 and V2 development strengthenings."""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest, load_instance
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_master import build_master_model
from scripts.validate_small_benchmarks import TOL, validate_result
from solve_direct_gurobi import solve_direct_gurobi
from solver_true_benders import solve_bbc_phase

OUTPUT = Path("validation/candidate_v2_exact")
CONFIGS = ("algorithm-candidate-v1", "V2A_valid", "V2B_pod_size_aggregate", "V2C_pod_size_aggregate_valid")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def cases():
    values = [(name, build_builtin_instance(name), 30) for name in ("tiny", "tiny_concentration")]
    root = Path("benchmarks/paper_exp_v1_pilot21_exact")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    values.extend((row["instance_id"], load_instance(root / row["relative_path"]), 90) for row in manifest["instances"])
    return values


def solve_config(data, config, budget):
    return solve_bbc_phase(data, Weights(), time_limit=budget, mip_gap=0, threads=1, seed=0,
                           warm_start=False, add_valid_inequalities=config["valid_inequalities"],
                           valid_inequality_profile=config.get("valid_inequality_profile", "common"),
                           aggregate_recourse_lb=config["aggregate_recourse_lb"],
                           aggregate_relaxation_level=config.get("aggregate_relaxation_level", "size"),
                           analytic_recourse_lb=config["analytic_recourse_lb"], node_cuts=False,
                           cut_strategy="standard", origin_prefix=config["configuration_name"])


def fixed_bound(data, solution, level, valid=False):
    model, variables, context = build_master_model(
        data, Weights(), relax=True, add_valid_inequalities=valid,
        valid_inequality_profile="common", aggregate_recourse_lb=True,
        aggregate_relaxation_level=level, analytic_recourse_lb=False)
    for key, variable in variables["x"].items(): variable.LB = variable.UB = float(solution["x"].get(key, 0))
    for key, variable in variables["alloc_boxes"].items(): variable.LB = variable.UB = float(solution["alloc_boxes"].get(key, 0))
    model.optimize()
    value = float(variables["eta"].X) if model.SolCount else None
    diagnostics = context["master_strengthening"]
    model.dispose(); return value, diagnostics


def reference_direct_objectives():
    report = json.loads(Path("validation/pilot21_exact_fixtures/report.json").read_text(encoding="utf-8"))
    return {item["instance_id"]: item["methods"]["direct"]["ub"] for item in report["instances"]}


def create_report(rows, planned):
    references = reference_direct_objectives(); instances = []
    for instance, _, _ in cases():
        group = [row for row in rows if row["instance_id"] == instance]
        by_method = {row["method"]: row for row in group}
        direct = by_method.get("direct"); errors = []
        if direct is None: errors.append("missing Direct")
        elif direct["errors"] or not direct["optimal"]: errors.append("Direct failed")
        elif abs(direct["ub"] - references[instance]) > TOL: errors.append("Direct optimum changed")
        for name in CONFIGS:
            row = by_method.get(name)
            if row is None: errors.append(f"missing {name}")
            elif row["errors"] or not row["optimal"]: errors.append(f"{name} failed")
            elif direct and abs(row["ub"] - direct["ub"]) > TOL: errors.append(f"{name} optimum mismatch")
            elif row["lb"] is not None and direct and row["lb"] > direct["ub"] + TOL: errors.append(f"{name} LB exceeds optimum")
        dominance = direct and direct.get("pod_size_bound") is not None and direct["pod_size_bound"] + TOL >= direct["size_bound"]
        valid_domain = direct and direct.get("valid_fixed_point_feasible", False)
        if not dominance: errors.append("POD-size bound does not dominate size")
        if not valid_domain: errors.append("common inequalities reject Direct optimum")
        instances.append({"instance_id": instance, "status": "PASS" if not errors else "FAIL",
                          "errors": errors, "pod_size_dominates_size": bool(dominance),
                          "common_valid_preserves_direct_optimum": bool(valid_domain), "methods": by_method})
    complete = len(rows) == 5 * (1 + len(CONFIGS))
    payload = {"status": "PASS" if complete and all(item["status"] == "PASS" for item in instances) else "FAIL",
               "completed_runs": len(rows), "planned_runs": 25, "planned_budget_seconds": planned,
               "actual_runtime_seconds": sum(row["actual_runtime"] for row in rows), "instances": instances,
               "candidate_algorithm_frozen": True, "candidate_v2_frozen": False, "final_algorithm_frozen": False}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "report.md").write_text("# Candidate-v2 exact gate\n\n" + f"Overall: **{payload['status']}**\n\n"
        f"Runs: {len(rows)}/25; planned budget: {planned}s; actual runtime: {payload['actual_runtime_seconds']:.3f}s.\n\n" +
        "\n".join(f"- {item['instance_id']}: {item['status']}" for item in instances) + "\n", encoding="utf-8")
    return payload


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True); source = OUTPUT / "results.jsonl"
    rows = read_jsonl(source); done = {(row["instance_id"], row["method"]) for row in rows}
    all_cases = cases(); planned = sum(budget * (1 + len(CONFIGS)) for _, _, budget in all_cases)
    for instance, raw, budget in all_cases:
        data = prepare_instance(raw)
        methods = ("direct", *CONFIGS)
        for method in methods:
            if (instance, method) in done: continue
            started = time.perf_counter(); exception = None
            try:
                result = solve_direct_gurobi(data, Weights(), time_limit=budget, mip_gap=0, threads=1, seed=0) if method == "direct" else solve_config(data, get_algorithm_configuration(method), budget)
                evaluation, errors, details = validate_result(data, result, "direct" if method == "direct" else "bbc")
                if method == "direct" and result.get("solution"):
                    size, size_diag = fixed_bound(data, result["solution"], "size")
                    pod, pod_diag = fixed_bound(data, result["solution"], "pod_size")
                    valid_value, valid_diag = fixed_bound(data, result["solution"], "size", valid=True)
                else: size = pod = valid_value = None; size_diag = pod_diag = valid_diag = None
            except Exception as exc:
                result = {}; evaluation = None; errors = [str(exc)]; details = {}; exception = traceback.format_exc()
                size = pod = valid_value = None; size_diag = pod_diag = valid_diag = None
            item = {"instance_id": instance, "digest": instance_digest(raw), "method": method,
                    "configuration_version": None if method == "direct" else get_algorithm_configuration(method)["configuration_version"],
                    "configuration_hash": None if method == "direct" else get_algorithm_configuration(method)["configuration_hash"],
                    "planned_budget": budget, "actual_runtime": time.perf_counter() - started,
                    "status_name": result.get("status_name"), "optimal": result.get("status_name") == "OPTIMAL" and (result.get("gap") or 0) <= TOL,
                    "solution_returned": bool(result.get("solution")), "ub": result.get("ub"), "lb": result.get("lb"), "gap": result.get("gap"),
                    "errors": errors, "details": details, "master_strengthening": result.get("master_diagnostics", {}).get("master_strengthening"),
                    "size_bound": size, "pod_size_bound": pod, "valid_fixed_point_feasible": valid_value is not None,
                    "fixed_point_diagnostics": {"size": size_diag, "pod_size": pod_diag, "valid": valid_diag}, "exception": exception}
            rows.append(item); write_jsonl(source, rows); report = create_report(rows, planned)
            print(instance, method, item["status_name"], "errors", errors, flush=True)
    final = create_report(rows, planned); return 0 if final["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())

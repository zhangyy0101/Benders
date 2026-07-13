"""Run the time-boxed Pilot2 fast internal component screen."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configurations import get_algorithm_configuration
from experiment_runner import read_jsonl, run_jobs


CONFIGS = (
    "C0_bbc_core", "C1_core_analytic", "C2_core_aggregate",
    "C3_core_both_lb", "C4_both_lb_root", "C5_both_lb_warm",
    "C6_both_lb_warm_alns", "C7_both_lb_root_warm_alns",
    "C8_both_lb_root_warm_alns_valid",
)
INSTANCES = ("S01", "M01", "L01")
PAIRS = (
    ("aggregate_lb", "C2_core_aggregate", "C0_bbc_core"),
    ("analytic_lb_alone", "C1_core_analytic", "C0_bbc_core"),
    ("analytic_lb_increment", "C3_core_both_lb", "C2_core_aggregate"),
    ("root_without_primal", "C4_both_lb_root", "C3_core_both_lb"),
    ("warm", "C5_both_lb_warm", "C3_core_both_lb"),
    ("alns", "C6_both_lb_warm_alns", "C5_both_lb_warm"),
    ("root_with_primal", "C7_both_lb_root_warm_alns", "C6_both_lb_warm_alns"),
    ("valid_inequalities", "C8_both_lb_root_warm_alns_valid", "C7_both_lb_root_warm_alns"),
)


def finite(value):
    return value is not None and math.isfinite(float(value))


def metric(row, key):
    if key == "feasible":
        return bool(row["status"]["feasible_incumbent_found"])
    if key == "runtime":
        return row["timing"].get("wall_clock")
    return row["optimization"].get(key)


def meaningful(candidate, baseline, direction, relative=0.01):
    if not finite(candidate) or not finite(baseline):
        return False
    delta = (float(candidate) - float(baseline)) * direction
    return delta > max(1e-8, abs(float(baseline)) * relative)


def improvement_flags(candidate, baseline):
    cf, bf = metric(candidate, "feasible"), metric(baseline, "feasible")
    return {
        "feasible": cf and not bf,
        "lb": meaningful(metric(candidate, "lb"), metric(baseline, "lb"), 1),
        "time_to_first_feasible": meaningful(
            metric(candidate, "time_to_first_feasible"),
            metric(baseline, "time_to_first_feasible"), -1, .05),
        "primal_integral": meaningful(metric(candidate, "primal_integral"), metric(baseline, "primal_integral"), -1, .05),
        "gap_integral": meaningful(metric(candidate, "gap_integral"), metric(baseline, "gap_integral"), -1, .05),
        "gap": meaningful(metric(candidate, "gap"), metric(baseline, "gap"), -1, .01),
        "ub": meaningful(metric(candidate, "ub"), metric(baseline, "ub"), -1, .01),
    }


def rows_by_key(rows):
    return {(r["identity"]["instance_id"], r["configuration"]["configuration_name"]): r for r in rows}


def write_csv(path, fieldnames, records):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def create_artifacts(rows, output, planned_budget):
    keyed = rows_by_key(rows)
    summary = []
    runtime = []
    for row in rows:
        identity, status, opt, timing = row["identity"], row["status"], row["optimization"], row["timing"]
        summary.append({
            "instance_id": identity["instance_id"], "configuration": identity["configuration_name"],
            "budget": identity["budget"], "status": status["status"],
            "feasible": status["feasible_incumbent_found"],
            "time_to_first_feasible": opt.get("time_to_first_feasible"),
            "primal_integral": opt.get("primal_integral"), "gap_integral": opt.get("gap_integral"),
            "final_gap": opt.get("gap"), "final_ub": opt.get("ub"), "final_lb": opt.get("lb"),
            "nodes": opt.get("nodes"), "cuts": opt.get("cuts"), "sp_solves": opt.get("sp_solves"),
            "alns_improvement": row.get("method_diagnostics", {}).get("alns", {}).get("improvement"),
            "exception": status["status"] == "EXCEPTION",
        })
        runtime.append({"instance_id": identity["instance_id"], "configuration": identity["configuration_name"],
                        **{key: timing.get(key) for key in ("wall_clock", "model_build", "solve", "root", "warm", "alns", "main", "callback", "sp_total")}})
    summary_fields = list(summary[0]) if summary else ["instance_id", "configuration"]
    runtime_fields = list(runtime[0]) if runtime else ["instance_id", "configuration"]
    write_csv(output / "screen_summary.csv", summary_fields, summary)
    write_csv(output / "runtime_breakdown.csv", runtime_fields, runtime)

    deltas = []
    component_scores = {}
    for component, candidate_name, baseline_name in PAIRS:
        score = {key: 0 for key in ("feasible", "lb", "time_to_first_feasible", "primal_integral", "gap_integral", "gap", "ub")}
        for instance in INSTANCES:
            candidate, baseline = keyed.get((instance, candidate_name)), keyed.get((instance, baseline_name))
            if candidate is None or baseline is None:
                continue
            flags = improvement_flags(candidate, baseline)
            for key, value in flags.items():
                score[key] += int(value)
            deltas.append({
                "component": component, "instance_id": instance, "candidate": candidate_name, "baseline": baseline_name,
                "candidate_feasible": metric(candidate, "feasible"), "baseline_feasible": metric(baseline, "feasible"),
                **{f"delta_{key}": (float(metric(candidate, key)) - float(metric(baseline, key)))
                   if finite(metric(candidate, key)) and finite(metric(baseline, key)) else None
                   for key in ("lb", "time_to_first_feasible", "primal_integral", "gap_integral", "gap", "ub")},
                **{f"improves_{key}": value for key, value in flags.items()},
            })
        component_scores[component] = score
    delta_fields = list(deltas[0]) if deltas else ["component", "instance_id"]
    write_csv(output / "paired_component_deltas.csv", delta_fields, deltas)

    complete = len(keyed) == len(INSTANCES) * len(CONFIGS)
    exceptions = sum(r["status"]["status"] == "EXCEPTION" for r in rows)
    retain_components, drop_components, needs = [], [], []
    if complete and not exceptions:
        aggregate = component_scores["aggregate_lb"]
        (retain_components if aggregate["lb"] + aggregate["gap_integral"] + aggregate["gap"] >= 2 else drop_components).append("aggregate_lb")
        analytic = component_scores["analytic_lb_increment"]
        (retain_components if analytic["lb"] + analytic["gap_integral"] + analytic["gap"] >= 2 else drop_components).append("analytic_lb")
        warm = component_scores["warm"]
        (retain_components if warm["feasible"] + warm["time_to_first_feasible"] + warm["primal_integral"] >= 2 else drop_components).append("warm_start")
        alns = component_scores["alns"]
        (retain_components if alns["feasible"] + alns["ub"] + alns["primal_integral"] >= 2 else drop_components).append("alns")
        root_score = sum(component_scores[name][key] for name in ("root_without_primal", "root_with_primal") for key in ("feasible", "gap_integral", "gap"))
        (retain_components if root_score >= 2 else drop_components).append("root_prepass")
        valid = component_scores["valid_inequalities"]
        (retain_components if valid["feasible"] + valid["ub"] + valid["primal_integral"] + valid["gap_integral"] + valid["gap"] >= 2 else drop_components).append("valid_inequalities")
    elif exceptions:
        needs.append("exception repair before a component decision")
    else:
        needs.append("remaining scheduled runs")

    best_lb = "C3_core_both_lb" if "aggregate_lb" in retain_components and "analytic_lb" in retain_components else "C2_core_aggregate" if "aggregate_lb" in retain_components else "C1_core_analytic" if "analytic_lb" in retain_components else "C0_bbc_core"
    recommended = ["C0_bbc_core", best_lb]
    if "warm_start" in retain_components:
        recommended.append("C5_both_lb_warm")
    if "alns" in retain_components:
        recommended.append("C6_both_lb_warm_alns")
    integrated = "C8_both_lb_root_warm_alns_valid" if "valid_inequalities" in retain_components else "C7_both_lb_root_warm_alns" if "root_prepass" in retain_components else "C6_both_lb_warm_alns"
    recommended.append(integrated)
    for fallback in ("C3_core_both_lb", "C5_both_lb_warm", "C6_both_lb_warm_alns", "C7_both_lb_root_warm_alns"):
        if len(dict.fromkeys(recommended)) >= 4:
            break
        recommended.append(fallback)
    recommended = list(dict.fromkeys(recommended))[:6]
    if not complete or exceptions:
        recommended = []
    dropped_configs = [name for name in CONFIGS if complete and name not in recommended]
    actual_runtime = sum(float(r["timing"]["wall_clock"]) for r in rows)
    payload = {
        "status": "COMPLETE" if complete and not exceptions else "NEEDS_CONFIRMATION" if exceptions else "PARTIAL",
        "retain_for_confirmation": retain_components,
        "drop": drop_components,
        "needs_confirmation": needs,
        "recommended_confirmation_configs": recommended,
        "dropped_configs": dropped_configs,
        "p3_configuration_count": len(recommended),
        "completed_runs": len(keyed), "planned_runs": 27,
        "planned_budget_seconds": planned_budget, "screen_runtime_seconds": actual_runtime,
        "exceptions": exceptions,
        "no_incumbent_runs": [f'{r["identity"]["instance_id"]}:{r["configuration"]["configuration_name"]}' for r in rows if not r["status"]["feasible_incumbent_found"]],
        "time_limit_runs_are_not_retried": True,
        "candidate_algorithm_frozen": False, "final_algorithm_frozen": False,
    }
    (output / "recommended_configs.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = ["# P2 fast internal component screen", "", f"Status: **{payload['status']}**", "",
              f"- Completed runs: {len(keyed)}/27", f"- Exceptions: {exceptions}",
              f"- Runtime represented by completed runs: {actual_runtime:.2f} seconds",
              f"- Retain for confirmation: {', '.join(retain_components) or 'pending'}",
              f"- Drop from main line: {', '.join(drop_components) or 'pending'}",
              f"- Recommended P3 configurations ({len(recommended)}): {', '.join(recommended) or 'pending'}",
              f"- Dropped configurations: {', '.join(dropped_configs) or 'pending'}",
              f"- Runs without an incumbent: {', '.join(payload['no_incumbent_runs']) or 'none'}", "",
              "Runs without an incumbent are retained as evidence of weaker first-feasible capability; they are not automatically extended or rerun.", "",
              "`candidate_algorithm_frozen: false`; `final_algorithm_frozen: false`." ]
    (output / "component_decision_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="benchmarks/paper_exp_v1_pilot21")
    parser.add_argument("--output", default="experiments/internal_screen_fast")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    root, output = Path(args.suite), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    selected = {row["instance_id"]: row for row in manifest["instances"] if row["instance_id"] in INSTANCES}
    budgets = {"S01": 20, "M01": 60, "L01": 180}
    jobs = []
    for instance in INSTANCES:
        row = selected[instance]
        base = {"instance_id": instance, "instance_path": root / row["relative_path"], "expected_digest": row["digest"],
                "seed": 0, "budget": budgets[instance], "threads": 1, "mip_gap": .05, "alloc_domain": "integer",
                "handling_rate_scale": 1.0, "outbound_policy": "proportional"}
        jobs.extend({**base, "method": "bbc_candidate", "configuration": get_algorithm_configuration(name)} for name in CONFIGS)
    planned = sum(job["budget"] for job in jobs)
    if args.analyze_only:
        final = create_artifacts(read_jsonl(output / "raw_results.jsonl"), output, planned)
        return 0 if final["status"] == "COMPLETE" else 1
    for job in jobs:
        # Completed time-limit runs are intentionally resumable and never rerun.
        rows = run_jobs([job], output, resume=args.resume, rerun_failed=False, save_solutions=False, source_filename="raw_results.jsonl")
        payload = create_artifacts(rows, output, planned)
        print(job["instance_id"], job["configuration"]["configuration_name"], payload["completed_runs"], flush=True)
    final = create_artifacts(read_jsonl(output / "raw_results.jsonl"), output, planned)
    return 0 if final["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())

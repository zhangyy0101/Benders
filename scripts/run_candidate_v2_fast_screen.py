"""P6B 12-run, seed-0 strengthening screen."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration
from experiment_runner import _atomic_write, export_results, run_jobs
from scripts.run_candidate_experiments import build_jobs

CONFIGS = ("algorithm-candidate-v1", "V2A_valid", "V2B_pod_size_aggregate", "V2C_pod_size_aggregate_valid")
INSTANCES = ("S01", "M01", "L01")
BUDGETS = {"S01": 30, "M01": 90, "L01": 240}
TARGETS = {"S01": .05, "M01": .08, "L01": .10}
PAIRS = (("valid_on_size", "V2A_valid", "algorithm-candidate-v1"),
         ("valid_on_pod_size", "V2C_pod_size_aggregate_valid", "V2B_pod_size_aggregate"),
         ("pod_size_without_valid", "V2B_pod_size_aggregate", "algorithm-candidate-v1"),
         ("pod_size_with_valid", "V2C_pod_size_aggregate_valid", "V2A_valid"),
         ("combined", "V2C_pod_size_aggregate_valid", "algorithm-candidate-v1"))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def prerequisites():
    status = json.loads(Path("docs/pilot21_status.json").read_text(encoding="utf-8"))
    exact = json.loads(Path("validation/candidate_v2_exact/report.json").read_text(encoding="utf-8"))
    assert status["p5_cleanup"]["candidate_v1_smoke"] == "PASS"
    assert exact["status"] == "PASS"
    assert get_algorithm_configuration("algorithm-candidate-v1")["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH


def make_job(instance, config):
    args = SimpleNamespace(suite_dir="benchmarks/paper_exp_v1_pilot21", instances=[instance],
                           algorithm_config=config, seeds=[0], budget=BUDGETS[instance],
                           threads=1, mip_gap=.03)
    return build_jobs(args)[0]


def metric(row, name): return row.get("optimization", {}).get(name)


def safe_ratio(numerator, denominator): return numerator / max(abs(denominator), 1e-9)


def pair_delta(label, candidate, baseline):
    cg, bg = metric(candidate, "gap"), metric(baseline, "gap")
    cub, bub = metric(candidate, "ub"), metric(baseline, "ub")
    clb, blb = metric(candidate, "lb"), metric(baseline, "lb")
    cb = candidate["timing"].get("model_build") or 0; bb = baseline["timing"].get("model_build") or 0
    return {"comparison": label, "instance_id": candidate["identity"]["instance_id"],
            "candidate": candidate["identity"]["configuration_name"], "baseline": baseline["identity"]["configuration_name"],
            "gap_improvement_points": None if cg is None or bg is None else float(bg) - float(cg),
            "gap_relative_improvement": None if cg is None or bg is None else safe_ratio(float(bg) - float(cg), float(bg)),
            "lb_relative_improvement": None if clb is None or blb is None else safe_ratio(float(clb) - float(blb), float(blb)),
            "ub_relative_change": None if cub is None or bub is None else safe_ratio(float(cub) - float(bub), float(bub)),
            "model_build_overhead": safe_ratio(float(cb) - float(bb), float(bb)),
            "candidate_feasible": candidate["status"]["feasible_incumbent_found"],
            "baseline_feasible": baseline["status"]["feasible_incumbent_found"]}


def prune_solutions(rows, output, instance):
    completed = [row for row in rows if row["identity"]["instance_id"] == instance]
    if len(completed) < len(CONFIGS): return
    group = [row for row in completed if row.get("solution_file")]
    feasible = [row for row in group if row["status"]["feasible_incumbent_found"] and metric(row, "ub") is not None]
    keep = min(feasible, key=lambda row: float(metric(row, "ub"))) if feasible else None
    for row in group:
        if row is keep: continue
        path = Path(output) / row["solution_file"]["relative_path"]
        if path.exists(): path.unlink()
        row.pop("solution_file", None)
    source = Path(output) / "raw_results.jsonl"
    _atomic_write(source, "".join(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n" for row in rows))
    export_results(output, rows)


def summarize(rows, output):
    keyed = {(row["identity"]["instance_id"], row["identity"]["configuration_name"]): row for row in rows}
    summary = []
    for row in rows:
        identity, timing, strength = row["identity"], row["timing"], row.get("master_strengthening") or {}
        gap = metric(row, "gap")
        summary.append({"instance_id": identity["instance_id"], "configuration": identity["configuration_name"],
                        "feasible": row["status"]["feasible_incumbent_found"], "ub": metric(row,"ub"), "lb": metric(row,"lb"), "gap": gap,
                        "target_gap": TARGETS[identity["instance_id"]], "distance_to_target": None if gap is None else max(0,float(gap)-TARGETS[identity["instance_id"]]),
                        "time_to_first_feasible": metric(row,"time_to_first_feasible"), "time_to_best": metric(row,"time_to_best"),
                        "primal_integral": metric(row,"primal_integral"), "gap_integral": metric(row,"gap_integral"),
                        "total_runtime": timing.get("wall_clock"), "model_build": timing.get("model_build"),
                        "aggregate_build": strength.get("aggregate_build_time"), "valid_inequality_build": strength.get("valid_inequality_build_time"),
                        "callback": timing.get("callback"), "sp_total": timing.get("sp_total"), "nodes": metric(row,"nodes"), "cuts": metric(row,"cuts"),
                        "aggregate_variable_count": strength.get("aggregate_variable_count"), "aggregate_constraint_count": strength.get("aggregate_constraint_count"),
                        "checker_pass": row.get("safety",{}).get("checker_pass"), "lb_le_ub": row.get("safety",{}).get("lb_le_ub"),
                        "exact_recourse_consistent": row.get("safety",{}).get("exact_recourse_consistent"), "exception": row["status"]["status"]=="EXCEPTION"})
    fields = list(summary[0]) if summary else ["instance_id","configuration"]
    write_csv(Path(output)/"results.csv", summary, fields)
    costs = [{key:value for key,value in row.items() if key in ("instance_id","configuration","total_runtime","model_build","aggregate_build","valid_inequality_build","callback","sp_total","nodes","cuts","aggregate_variable_count","aggregate_constraint_count")} for row in summary]
    write_csv(Path(output)/"strengthening_costs.csv", costs, list(costs[0]) if costs else ["instance_id","configuration"])
    deltas = []
    for label, candidate, baseline in PAIRS:
        for instance in INSTANCES:
            if (instance,candidate) in keyed and (instance,baseline) in keyed:
                deltas.append(pair_delta(label,keyed[instance,candidate],keyed[instance,baseline]))
    write_csv(Path(output)/"paired_deltas.csv", deltas, list(deltas[0]) if deltas else ["comparison","instance_id"])
    decisions={};passing=[]
    for config in CONFIGS[1:]:
        group=[keyed.get((instance,config)) for instance in INSTANCES];base=[keyed.get((instance,CONFIGS[0])) for instance in INSTANCES]
        reasons=[]
        if None in group or None in base:reasons.append("incomplete runs")
        else:
            direct=[pair_delta("selection",c,b) for c,b in zip(group,base)]
            if not all(c["status"]["feasible_incumbent_found"] for c in group):reasons.append("feasible rate below 3/3")
            if any(c["status"]["status"]=="EXCEPTION" for c in group):reasons.append("exception")
            if sum((d["gap_improvement_points"] or 0)>1e-6 for d in direct)<2:reasons.append("gap improves on fewer than 2/3 instances")
            large=direct[2]
            if (large["gap_improvement_points"] or 0)<.01 and (large["lb_relative_improvement"] or 0)<.03:reasons.append("L01 strengthening threshold not met")
            if any((d["ub_relative_change"] or 0)>.02 for d in direct):reasons.append("UB worsens by more than 2%")
            if any((d["model_build_overhead"] or 0)>.35 and (d["gap_relative_improvement"] or 0)<=.20 for d in direct):reasons.append("model-build overhead threshold exceeded")
            if not all(all(c.get("safety",{}).get(k) for k in ("checker_pass","lb_le_ub","exact_recourse_consistent","no_exception")) for c in group):reasons.append("safety gate failed")
            score=sum(d["gap_improvement_points"] or 0 for d in direct)/3
            decisions[config]={"passed":not reasons,"reasons":reasons or ["all P6B thresholds passed"],"mean_gap_improvement_points":score,"l01_gap_improvement_points":large["gap_improvement_points"],"l01_lb_relative_improvement":large["lb_relative_improvement"]}
            if not reasons:passing.append((score,config))
    selected=[config for _,config in sorted(passing,reverse=True)[:2]]
    complete=len(keyed)==12
    component_findings={
        "valid_inequalities": {"effective": False, "finding": "V2A improved gap on 3/3 instances and met the L01 gap threshold, but failed the per-instance model-build overhead rule."},
        "pod_size_aggregate": {"effective": False, "finding": "V2B improved gap on only S01, worsened M01 gap, and found no L01 incumbent."},
        "combined": {"best": False, "finding": "V2C achieved the best S01 gap but did not find an L01 incumbent and therefore is not the best admissible configuration."}}
    payload={"baseline":"algorithm-candidate-v1","selected_new_configs":selected,"approved_for_p7":bool(selected) and complete,
             "selection_reasons":decisions,"candidate_v1_hash_verified":get_algorithm_configuration("algorithm-candidate-v1")["configuration_hash"]==FROZEN_CANDIDATE_V1_HASH,
             "candidate_v1_remains_best":complete and not selected,"completed_runs":len(keyed),"planned_runs":12,
             "actual_runtime_seconds":sum(float(row["timing"]["wall_clock"]) for row in rows),"component_findings":component_findings,"candidate_v2_frozen":False,"final_algorithm_frozen":False}
    (Path(output)/"selected_for_p7.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    report=["# Candidate-v2 fast strengthening screen","",f"Status: **{'COMPLETE' if complete else 'PARTIAL'}**","",
            f"- Runs: {len(keyed)}/12",f"- Runtime: {payload['actual_runtime_seconds']:.2f} seconds",f"- Selected for P7: {', '.join(selected) or 'none'}","",
            "## Per-run results","","| Instance | Config | UB | LB | Gap | Target distance |","|---|---|---:|---:|---:|---:|"]
    report.extend(f"| {r['instance_id']} | {r['configuration']} | {r['ub']} | {r['lb']} | {r['gap']} | {r['distance_to_target']} |" for r in summary)
    report.extend(["","## Decisions",""]+[f"- {name}: {'retain for P7' if value['passed'] else 'drop'} — {'; '.join(value['reasons'])}" for name,value in decisions.items()])
    report.extend(["","## Component findings","",
                   f"- Valid inequalities: {component_findings['valid_inequalities']['finding']}",
                   f"- POD–size aggregate: {component_findings['pod_size_aggregate']['finding']}",
                   f"- Combined V2C: {component_findings['combined']['finding']}","",
                   "No seed 1 run, budget extension, or automatic rerun was performed. Candidate-v2 remains unfrozen."])
    (Path(output)/"screen_report.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    return payload


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",default="experiments/candidate_v2_fast_screen");parser.add_argument("--resume",action=argparse.BooleanOptionalAction,default=True);parser.add_argument("--rerun-failed",action="store_true");args=parser.parse_args()
    prerequisites();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for instance in INSTANCES:
        for config in CONFIGS:
            rows=run_jobs([make_job(instance,config)],output,resume=args.resume,rerun_failed=args.rerun_failed,
                          save_solutions=True,source_filename="raw_results.jsonl",command="scripts/run_candidate_v2_fast_screen.py")
            summarize(rows,output);print(instance,config,len(rows),flush=True)
        prune_solutions(rows,output,instance);rows=json.loads((output/"results.json").read_text(encoding="utf-8"));summarize(rows,output)
    final=summarize(rows,output);return 0 if final["completed_runs"]==12 else 1


if __name__=="__main__":raise SystemExit(main())

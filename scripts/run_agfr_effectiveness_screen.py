"""Fair same-budget seed-0 comparison of frozen BBC and adaptive AGFR+BBC."""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest, load_instance
from experiment_runner import read_jsonl, run_jobs

DEFAULT_BUDGETS = {"S01": 30.0, "M01": 60.0, "L01": 120.0}


def instance_path(root, iid):
    size = {"S01": "small", "M01": "medium", "L01": "large"}[iid]
    return root / size / f"{iid}.json"


def make_job(root, iid, budget, configuration):
    path = instance_path(root, iid); digest = instance_digest(load_instance(path))
    return {"instance_id": iid, "instance_path": path, "expected_digest": digest,
            "method": "bbc_candidate", "configuration": configuration, "seed": 0,
            "budget": budget, "threads": 1, "mip_gap": .03, "alloc_domain": "integer",
            "handling_rate_scale": 1.0, "outbound_policy": "proportional"}


def summarize(rows, output, budgets):
    current={name:get_algorithm_configuration(name)["configuration_hash"] for name in ("algorithm-candidate-v1","candidate-v2-agfr-development")}
    selected = {(row["identity"]["instance_id"], row["identity"]["configuration_name"]): row for row in rows
                if row["identity"].get("configuration_hash")==current.get(row["identity"].get("configuration_name"))}
    comparisons=[]
    for iid in budgets:
        base=selected.get((iid,"algorithm-candidate-v1"));agfr=selected.get((iid,"candidate-v2-agfr-development"))
        if not base or not agfr: continue
        bu,au=base["optimization"]["ub"],agfr["optimization"]["ub"];bl,al=base["optimization"]["lb"],agfr["optimization"]["lb"]
        row={"instance_id":iid,"budget":budgets[iid],"baseline_ok":base["status"]["ok"],"agfr_ok":agfr["status"]["ok"],
             "baseline_ub":bu,"agfr_ub":au,"ub_improvement":None if bu is None or au is None else bu-au,
             "ub_improvement_pct":None if bu is None or au is None else 100*(bu-au)/max(abs(bu),1e-9),
             "baseline_lb":bl,"agfr_lb":al,"baseline_gap":base["optimization"]["gap"],"agfr_gap":agfr["optimization"]["gap"],
             "gap_reduction":None if base["optimization"]["gap"] is None or agfr["optimization"]["gap"] is None else base["optimization"]["gap"]-agfr["optimization"]["gap"],
             "baseline_first_feasible":base["optimization"].get("time_to_first_feasible"),"agfr_first_feasible":agfr["optimization"].get("time_to_first_feasible"),
             "baseline_primal_integral":base["optimization"].get("primal_integral"),"agfr_primal_integral":agfr["optimization"].get("primal_integral"),
             "repair":agfr.get("repair"),"baseline_source":base["optimization"].get("solution_source"),"agfr_source":agfr["optimization"].get("solution_source")}
        row["ub_better"]=row["ub_improvement"] is not None and row["ub_improvement"]>1e-5
        row["gap_better"]=row["gap_reduction"] is not None and row["gap_reduction"]>1e-7
        comparisons.append(row)
    complete=len(comparisons)==len(budgets);safe=complete and all(r["baseline_ok"] and r["agfr_ok"] and (r["repair"] or {}).get("ok") is True for r in comparisons)
    effective=safe and any(r["ub_better"] for r in comparisons) and sum(r["ub_better"] for r in comparisons)>=sum((r["ub_improvement"] or 0)<-1e-5 for r in comparisons)
    report={"status":"PASS" if effective else "FAIL","effective_ub_improvement":bool(effective),"complete":complete,"safe":safe,"budgets":budgets,"comparisons":comparisons}
    output.mkdir(parents=True,exist_ok=True);(output/"effectiveness_report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    lines=["# Adaptive AGFR effectiveness screen","",f"Status: **{report['status']}**","", "| Instance | Budget | Baseline UB | AGFR UB | UB improvement | Baseline gap | AGFR gap |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in comparisons:lines.append(f"| {r['instance_id']} | {r['budget']:.0f} | {r['baseline_ub']} | {r['agfr_ub']} | {r['ub_improvement']} | {r['baseline_gap']} | {r['agfr_gap']} |")
    (output/"effectiveness_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8");return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--suite",type=Path,default=Path("benchmarks/paper_exp_v1_pilot21"));p.add_argument("--output",type=Path,default=Path("validation/agfr_effectiveness"));p.add_argument("--resume",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--instances",nargs="+",choices=tuple(DEFAULT_BUDGETS),default=list(DEFAULT_BUDGETS));a=p.parse_args(argv)
    budgets={iid:DEFAULT_BUDGETS[iid] for iid in a.instances};configs=[get_algorithm_configuration("algorithm-candidate-v1"),get_algorithm_configuration("candidate-v2-agfr-development")];jobs=[make_job(a.suite,iid,budgets[iid],config) for iid in budgets for config in configs]
    for job in jobs:
        run_jobs([job],a.output,resume=a.resume,rerun_failed=False,save_solutions=False,source_filename="raw_results.jsonl",export_derived=False,command="scripts/run_agfr_effectiveness_screen.py")
    report=summarize(read_jsonl(a.output/"raw_results.jsonl"),a.output,budgets);print(json.dumps(report,indent=2));return 0 if report["status"]=="PASS" else 1


if __name__=="__main__":raise SystemExit(main())

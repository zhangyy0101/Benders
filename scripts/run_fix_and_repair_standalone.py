"""Run the standalone AGFR safety, runtime, domain, and quality gate."""
from __future__ import annotations

import argparse, csv, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from benchmark_io import load_instance
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from solver_fix_and_repair import solve_aggregate_guided_fix_and_repair

DEFAULTS={"tiny":3,"tiny_concentration":3,"XS01":3,"XS02":3,"XS03":3,"S01":3,"M01":8,"L01":20}
ALL=tuple(DEFAULTS)
def raw(iid,suite):
 if iid in {"tiny","tiny_concentration"}:return build_builtin_instance(iid)
 if iid.startswith("XS"):return load_instance("benchmarks/paper_exp_v1_pilot21_exact"+f"/{iid}.json")
 size={"S01":"small","M01":"medium","L01":"large"}[iid];return load_instance(suite/size/f"{iid}.json")
def write_csv(path,rows,fields):
 with path.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:r.get(k) for k in fields} for r in rows)
def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument("--suite-dir",type=Path,default=Path("benchmarks/paper_exp_v1_pilot21"));p.add_argument("--instances",nargs="+",choices=ALL,default=ALL);p.add_argument("--budget-small",type=float,default=3);p.add_argument("--budget-medium",type=float,default=8);p.add_argument("--budget-large",type=float,default=20);p.add_argument("--seeds",nargs="+",type=int,default=[0]);p.add_argument("--threads",type=int,default=1);p.add_argument("--mip-gap",type=float,default=.05);p.add_argument("--output",type=Path,default=Path("validation/agfr_standalone"));p.add_argument("--resume",action=argparse.BooleanOptionalAction,default=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 budgets={**DEFAULTS,"S01":a.budget_small,"M01":a.budget_medium,"L01":a.budget_large};source=a.output/"raw_results.jsonl";existing=[]
 if a.resume and source.exists():existing=[json.loads(x) for x in source.read_text(encoding="utf-8").splitlines() if x.strip()]
 done={(r["instance_id"],r["seed"]) for r in existing};rows=list(existing)
 for iid in a.instances:
  for seed in a.seeds:
   if (iid,seed) in done:continue
   try:
    result=solve_aggregate_guided_fix_and_repair(prepare_instance(raw(iid,a.suite_dir)),Weights(),time_limit=budgets[iid],threads=a.threads,seed=seed,mip_gap=a.mip_gap)
    domain=(result.get("candidate_domain") or {}).get("diagnostics",{});selected=result.get("selected_attempt");attempt=None if selected is None else result["repair_attempts"][selected];evaluation=result.get("evaluation") or {};components=evaluation.get("components",{});first_time=next((e["time"] for e in result.get("anytime_trace",[]) if e["source"]=="restricted_monolithic_incumbent"),None)
    row={"instance_id":iid,"seed":seed,"budget":budgets[iid],"ok":result["ok"],"status_name":result["status_name"],"runtime":result["runtime"],"ub":result["ub"],"guide_source":result["guide"]["source"],"selected_attempt":selected,"expansion_level":None if attempt is None else attempt["expansion_level"],"candidate_pair_ratio":domain.get("candidate_pair_ratio"),"restricted_variable_ratio":None if attempt is None else attempt["restricted_variable_count"]/max(1,attempt["estimated_full_variable_count"]),"joint_coverage_status":domain.get("joint_coverage_status"),"soft_cap_exceptions":len(domain.get("forced_soft_cap_exceptions",[])),"time_to_first_repair_incumbent":first_time,"checker_pass":bool(attempt and attempt["checker"]["feasible"]),"objective_consistent":bool(attempt and abs(attempt["repair_objective"]-attempt["evaluation"]["core_cost"])<=1e-5),"oracle_consistent":result["oracle_consistent"],"open":components.get("open",{}).get("weighted"),"concentration":components.get("concentration",{}).get("weighted"),"distance":components.get("distance",{}).get("weighted"),"balance":components.get("balance",{}).get("weighted"),"conflict":components.get("conflict",{}).get("weighted"),"repair_attempts":[{"attempt":x["attempt"],"level":x["expansion_level"],"coverage":x["coverage_status"],"status":x["status_name"],"ok":x["ok"],"ratio":x["candidate_pair_ratio"]} for x in result["repair_attempts"]],"exception":None}
   except Exception as exc:row={"instance_id":iid,"seed":seed,"budget":budgets[iid],"ok":False,"status_name":"EXCEPTION","runtime":None,"ub":None,"exception":f"{type(exc).__name__}: {exc}"}
   rows.append(row);source.write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8");print(iid,seed,row["ok"],row["status_name"],row.get("candidate_pair_ratio"),flush=True)
 selected=[r for r in rows if r["instance_id"] in a.instances and r["seed"] in a.seeds];limits={i:(3.5 if i in {"tiny","tiny_concentration","XS01","XS02","XS03","S01"} else 9 if i=="M01" else 22) for i in ALL};ratios=[r.get("candidate_pair_ratio") for r in selected if r.get("candidate_pair_ratio") is not None];median=sorted(ratios)[len(ratios)//2] if ratios else None
 safety=all(r.get("ok") and not r.get("exception") and r.get("checker_pass") and r.get("objective_consistent") and r.get("oracle_consistent") for r in selected);runtime=all(r.get("runtime") is not None and r["runtime"]<=limits[r["instance_id"]] for r in selected);domain=all(r.get("candidate_pair_ratio") is not None and r["candidate_pair_ratio"]<1 for r in selected) and median is not None and median<=.60;complete=len(selected)==len(a.instances)*len(a.seeds);passed=complete and safety and runtime and domain
 gate={"status":"PASS" if passed else "FAIL","approved_for_bbc_integration":bool(passed),"complete":complete,"safety_pass":safety,"runtime_pass":runtime,"domain_reduction_pass":domain,"median_candidate_pair_ratio":median,"runs":selected};(a.output/"gate_report.json").write_text(json.dumps(gate,indent=2)+"\n",encoding="utf-8")
 (a.output/"gate_report.md").write_text(f"# Standalone AGFR gate\n\nStatus: **{gate['status']}**\n\n- Approved for BBC integration: `{str(passed).lower()}`\n- Safety: {safety}\n- Runtime: {runtime}\n- Domain reduction: {domain}\n- Median pair ratio: {median}\n",encoding="utf-8")
 flat=[k for k in selected[0] if k not in {"repair_attempts"}] if selected else [];write_csv(a.output/"results.csv",selected,flat);write_csv(a.output/"guide_diagnostics.csv",selected,["instance_id","seed","guide_source"]);write_csv(a.output/"candidate_domain.csv",selected,["instance_id","seed","candidate_pair_ratio","joint_coverage_status","soft_cap_exceptions","expansion_level"]);write_csv(a.output/"repair_attempts.csv",[{"instance_id":r["instance_id"],**x} for r in selected for x in r.get("repair_attempts",[])],["instance_id","attempt","level","coverage","status","ok","ratio"]);write_csv(a.output/"model_size.csv",selected,["instance_id","seed","restricted_variable_ratio","candidate_pair_ratio"]);return 0 if passed else 1
if __name__=="__main__":raise SystemExit(main())

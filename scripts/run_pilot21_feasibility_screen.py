from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from algorithm_configurations import get_algorithm_configuration
from experiment_runner import read_jsonl,run_jobs
from run_experiments import _simple_configuration
BBC=("C0_bbc_core","C2_core_aggregate","C3_core_both_lb","C5_both_lb_warm","C6_both_lb_warm_alns","C7_both_lb_root_warm_alns","C8_both_lb_root_warm_alns_valid")
def summarize(rows,output,planned,quick):
 counts={iid:{"runs":0,"feasible":0,"exceptions":0} for iid in ("S01","M01","L01")};families={"direct":False,"classical_benders":False,"bbc_candidate":False,"alns":False}
 for r in rows:
  iid=r["identity"]["instance_id"];counts[iid]["runs"]+=1;counts[iid]["feasible"]+=int(r["status"]["feasible_incumbent_found"]);counts[iid]["exceptions"]+=int(r["status"]["status"]=="EXCEPTION");trace=r.get("anytime_trace",[]);family=r["identity"]["method_family"]
  if len(trace)>1:families[family]=True
  if any(x.get("phase")=="alns" for x in trace):families["alns"]=True
 thresholds={"S01":8,"M01":6,"L01":4};complete=len(rows)==27;passed=complete and all(counts[i]["feasible"]>=thresholds[i] and counts[i]["exceptions"]==0 for i in counts) and all(families.values()) and all(all(k in r["optimization"] for k in ("primal_integral","gap_integral")) for r in rows)
 payload={"status":"PASS" if passed else "PARTIAL" if not complete else "FAIL","quick":quick,"planned_budget_seconds":planned,"actual_runtime_seconds":sum(r["timing"]["wall_clock"] for r in rows),"counts":counts,"non_final_only_trace_by_family":families,"pi_gi_present":all(all(k in r["optimization"] for k in ("primal_integral","gap_integral")) for r in rows),"candidate_algorithm_frozen":False,"final_algorithm_frozen":False};out=Path(output);(out/"screen_report.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8");(out/"screen_report.md").write_text(f"# Pilot2.1 feasibility screen\n\nStatus: **{payload['status']}**\n\n"+"\n".join(f"- {i}: {v['feasible']}/{v['runs']} feasible, {v['exceptions']} exceptions" for i,v in counts.items())+"\n",encoding="utf-8");return payload
def main():
 p=argparse.ArgumentParser();p.add_argument("--quick",action="store_true");p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot21");p.add_argument("--output",default="experiments/pilot21_feasibility_screen");p.add_argument("--resume",action=argparse.BooleanOptionalAction,default=True);a=p.parse_args();budgets={"S01":10 if a.quick else 15,"M01":30 if a.quick else 45,"L01":60 if a.quick else 120};root=Path(a.suite);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));selected={r["instance_id"]:r for r in manifest["instances"] if r["instance_id"] in budgets};jobs=[]
 for iid,row in selected.items():
  base={"instance_id":iid,"instance_path":root/row["relative_path"],"expected_digest":row["digest"],"seed":0,"budget":budgets[iid],"threads":1,"mip_gap":.10,"alloc_domain":"integer","handling_rate_scale":1.0,"outbound_policy":"proportional"}
  jobs.extend(({**base,"method":m,"configuration":_simple_configuration(m)} for m in ("direct","classical_benders")));jobs.extend({**base,"method":"bbc_candidate","configuration":get_algorithm_configuration(c)} for c in BBC)
 out=Path(a.output);out.mkdir(parents=True,exist_ok=True);planned=sum(x["budget"] for x in jobs)
 for job in jobs:
  rows=run_jobs([job],out,resume=a.resume,rerun_failed=False,save_solutions=False,source_filename="raw_results.jsonl");payload=summarize(rows,out,planned,a.quick);print(job["instance_id"],job["configuration"]["configuration_name"],payload["counts"][job["instance_id"]],flush=True)
 final=summarize(read_jsonl(out/"raw_results.jsonl"),out,planned,a.quick);return 0 if final["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())

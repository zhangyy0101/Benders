"""Timeboxed exact-fixture and formal-Small mathematical validation gates."""
from __future__ import annotations
import argparse,json,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from gurobipy import GRB
from benchmark_io import instance_digest,load_instance
from config import Weights
from cut_validation import validate_optimality_cut
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_recourse import GlobalRecourseOracle
from solution_evaluation import evaluate_common_solution
from solve_direct_gurobi import solve_direct_gurobi
from solver_true_benders import solve_bbc_phase
TOL=1e-5

def read_jsonl(path):
 p=Path(path);return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
def write_jsonl(path,rows):Path(path).write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in rows),encoding="utf-8")
def trace_valid(result):
 t=result.get("anytime_trace",[])
 if len(t)<2 or t[-1]["phase"]!="final":return False
 for key in ("ub","lb"):
  a,b=t[-1][key],result.get(key)
  if (a is None)!=(b is None) or a is not None and abs(a-b)>TOL:return False
 return all(a["time"]<=b["time"] for a,b in zip(t,t[1:])) and all(a>=b for a,b in zip([x["ub"] for x in t if x["ub"] is not None],[x["ub"] for x in t if x["ub"] is not None][1:])) and all(a<=b for a,b in zip([x["lb"] for x in t if x["lb"] is not None],[x["lb"] for x in t if x["lb"] is not None][1:]))
def validate_result(data,result,method):
 errors=[];evaluation=None;details={"trace_valid":trace_valid(result)}
 if not details["trace_valid"]:errors.append("invalid anytime trace")
 if result.get("solution"):
  evaluation=evaluate_common_solution(data,Weights(),result["solution"])
  if not evaluation["feasibility"]["feasible"]:errors.append("independent checker failed")
  if result.get("ub") is None or abs(result["ub"]-evaluation["core_cost"])>TOL:errors.append("UB/evaluator mismatch")
  if method=="direct" and abs(result["solver_objective"]-evaluation["core_cost"])>TOL:errors.append("solver/evaluator mismatch")
  point={"x":result["solution"]["x"],"alloc_boxes":result["solution"]["alloc_boxes"],"eta":evaluation["recourse_cost"]};oracle=GlobalRecourseOracle(data,Weights());oracle.update_rhs(point["x"],point["alloc_boxes"]);status=oracle.solve();details["oracle_status"]=int(status)
  if status!=GRB.OPTIMAL:errors.append("oracle not optimal")
  else:
   q=oracle.objective_value();details["oracle_recourse"]=q
   if abs(q-evaluation["recourse_cost"])>TOL:errors.append("oracle/evaluator recourse mismatch")
   cut=oracle.build_optimality_cut(point,"timeboxed_gate");details["cut_tightness_error"]=abs(cut.value_at({**point,"eta":q}));validation=validate_optimality_cut(data,Weights(),cut,[point]);details["cut_validation"]=validation
   if details["cut_tightness_error"]>TOL or not validation["valid"]:errors.append("cut validation failed")
  oracle.model.dispose()
 else:errors.append("no feasible incumbent")
 if result.get("ub") is not None and result.get("lb") is not None and result["lb"]>result["ub"]+TOL:errors.append("LB exceeds UB")
 return evaluation,errors,details
def solve(method,data,budget,threads,gap):
 if method=="direct":return solve_direct_gurobi(data,Weights(),time_limit=budget,mip_gap=gap,threads=threads,seed=0)
 return solve_bbc_phase(data,Weights(),time_limit=budget,mip_gap=gap,threads=threads,seed=0,add_valid_inequalities=False,aggregate_recourse_lb=False,analytic_recourse_lb=False,node_cuts=False,warm_start=False,origin_prefix="timeboxed_core")
def cases(args):
 if args.mode=="exact-fixtures":
  values=[]
  for name in ("tiny","tiny_concentration"):
   raw=build_builtin_instance(name);values.append((name,raw,30))
  root=Path("benchmarks/paper_exp_v1_pilot21_exact");manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
  for row in manifest["instances"]:values.append((row["instance_id"],load_instance(root/row["relative_path"]),args.time_limit_xs))
  return values
 root=Path(args.suite);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));limits={"S01":args.time_limit_s01,"S02":args.time_limit_other,"S03":args.time_limit_other};return [(r["instance_id"],load_instance(root/r["relative_path"]),limits[r["instance_id"]]) for r in manifest["instances"] if r["instance_id"] in limits]
def report(out,mode,rows,planned):
 by={}
 for row in rows:by.setdefault(row["instance_id"],{})[row["method"]]=row
 instances=[]
 for iid,methods in sorted(by.items()):
  complete=all(x in methods for x in ("direct","bbc_core"));objectives=[methods[x].get("ub") for x in ("direct","bbc_core") if x in methods and methods[x].get("ub") is not None];same=len(objectives)==2 and abs(objectives[0]-objectives[1])<=TOL
  if mode=="exact-fixtures":passed=complete and same and all(methods[x]["optimal"] and not methods[x]["errors"] for x in methods)
  else:passed=complete and all(not methods[x]["exception"] and (not methods[x].get("solution_returned") or not methods[x]["errors"]) for x in methods);passed=passed and any(methods[x].get("solution_returned") for x in methods)
  instances.append({"instance_id":iid,"status":"PASS" if passed else "FAIL","objective_consistent":same,"methods":methods})
 if mode=="exact-fixtures":overall=all(x["status"]=="PASS" for x in instances) and len(instances)==5
 else:overall=all(not m["exception"] for x in instances for m in x["methods"].values()) and sum(all(x["methods"].get(m,{}).get("solution_returned") for m in ("direct","bbc_core")) for x in instances)>=2 and all(x["status"]=="PASS" for x in instances)
 payload={"mode":mode,"status":"PASS" if overall else "FAIL","planned_budget_seconds":planned,"actual_runtime_seconds":sum(r["actual_runtime"] for r in rows),"candidate_algorithm_frozen":False,"final_algorithm_frozen":False,"instances":instances};(out/"report.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(out/"report.md").write_text(f"# {mode}\n\nOverall: **{payload['status']}**\n\nPlanned budget: {planned}s; actual runtime: {payload['actual_runtime_seconds']:.3f}s.\n\n"+"\n".join(f"- {x['instance_id']}: {x['status']}" for x in instances)+"\n",encoding="utf-8");return payload
def main():
 p=argparse.ArgumentParser();p.add_argument("--mode",choices=("exact-fixtures","formal-small-finite-time"),required=True);p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot21");p.add_argument("--time-limit-xs",type=float,default=90);p.add_argument("--time-limit-s01",type=float,default=90);p.add_argument("--time-limit-other",type=float,default=60);p.add_argument("--threads",type=int,default=1);p.add_argument("--resume",action="store_true");p.add_argument("--output",required=True);a=p.parse_args();out=Path(a.output);out.mkdir(parents=True,exist_ok=True);source=out/"results.jsonl";rows=read_jsonl(source) if a.resume else [];done={(x["instance_id"],x["method"]) for x in rows};all_cases=cases(a);planned=sum(2*b for _,_,b in all_cases)
 for iid,raw,budget in all_cases:
  if instance_digest(raw) is None:raise AssertionError("digest unavailable")
  for method in ("direct","bbc_core"):
   if (iid,method) in done:continue
   started=time.perf_counter();exception=None
   try:
    data=prepare_instance(raw);result=solve(method,data,budget,a.threads,0 if a.mode=="exact-fixtures" else .05);evaluation,errors,details=validate_result(data,result,method)
   except Exception as exc:result={};evaluation=None;errors=[str(exc)];details={};exception=traceback.format_exc()
   actual=time.perf_counter()-started;item={"instance_id":iid,"digest":instance_digest(raw),"method":method,"planned_budget":budget,"actual_runtime":actual,"status_name":result.get("status_name"),"optimal":result.get("status_name")=="OPTIMAL" and (result.get("gap") or 0)<=TOL,"solution_returned":bool(result.get("solution")),"ub":result.get("ub"),"lb":result.get("lb"),"gap":result.get("gap"),"errors":errors,"details":details,"anytime_trace":result.get("anytime_trace",[]),"exception":exception};rows.append(item);write_jsonl(source,rows);partial=report(out,a.mode,rows,planned);print(iid,method,item["status_name"],"errors",errors,flush=True)
   if a.mode=="exact-fixtures" and iid.startswith("XS") and not item["optimal"] and budget<180:
    # One permitted retry, replacing this run atomically.
    rows.pop();write_jsonl(source,rows);budget=180;started=time.perf_counter();data=prepare_instance(raw);result=solve(method,data,budget,a.threads,0);evaluation,errors,details=validate_result(data,result,method);item.update(planned_budget=budget,actual_runtime=time.perf_counter()-started,status_name=result.get("status_name"),optimal=result.get("status_name")=="OPTIMAL" and (result.get("gap") or 0)<=TOL,solution_returned=bool(result.get("solution")),ub=result.get("ub"),lb=result.get("lb"),gap=result.get("gap"),errors=errors,details=details,anytime_trace=result.get("anytime_trace",[]),exception=None);rows.append(item);write_jsonl(source,rows);report(out,a.mode,rows,planned+90);print(iid,method,"retry",item["status_name"],flush=True)
 final=report(out,a.mode,rows,planned);return 0 if final["status"]=="PASS" else 1
if __name__=="__main__":raise SystemExit(main())

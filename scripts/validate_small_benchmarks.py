"""Exact small-instance crosscheck and long-term mathematical regression gate."""
from __future__ import annotations
import argparse,csv,hashlib,json,sys,time,traceback
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
from solver_true_benders import solve_bbc_phase,solve_true_benders_pipeline

TOL=1e-5
FIELDS="instance digest method algorithm_status status runtime ub lb gap feasible max_violation objective open concentration distance balance conflict nodes cuts sp_solves result_status message".split()

def solution_digest(solution):
    def serial(value):
        if isinstance(value,dict):return sorted([(repr(k),serial(v)) for k,v in value.items()])
        if isinstance(value,(list,tuple)):return [serial(v) for v in value]
        return round(value,10) if isinstance(value,float) else value
    return hashlib.sha256(json.dumps(serial(solution),separators=(",",":")).encode()).hexdigest()

def check_solution(data,weights,result,method):
    failures=[];evaluation=None
    if result.get("ub") is not None and not result.get("solution"):failures.append("UB reported without solution")
    if result.get("solution"):
        evaluation=evaluate_common_solution(data,weights,result["solution"],tolerance=TOL)
        if not evaluation["feasibility"]["feasible"]:failures.append(f"infeasible solution: {evaluation['feasibility']}")
        values=[evaluation["components"][name]["weighted"] for name in ("open","concentration","distance","balance","conflict")]
        if abs(sum(values)-evaluation["core_cost"])>TOL:failures.append("component sum mismatch")
        if abs(evaluation["objective"]["first_stage"]+evaluation["objective"]["recourse"]-evaluation["core_cost"])>TOL:failures.append("first-stage + recourse mismatch")
        if result.get("ub") is not None and abs(result["ub"]-evaluation["core_cost"])>TOL:failures.append("reported UB/evaluator mismatch")
        if method=="direct" and abs(result["solver_objective"]-evaluation["core_cost"])>TOL:failures.append("solver/evaluator objective mismatch")
        concentration=evaluation["concentration"]
        if concentration["enabled"] and "concentration_use" in result["solution"]:
            modeled=sum(result["solution"]["concentration_use"].values())
            if abs(modeled-concentration["raw_used_bays"])>TOL:failures.append("modeled/evaluator concentration raw mismatch")
            for (j,g,i),value in result["solution"]["concentration_use"].items():
                expected=float(i in concentration["used_bays"].get((j,g),[]))
                if abs(value-expected)>TOL:failures.append(f"concentration support mismatch {(j,g,i)}");break
    if result.get("ub") is not None and result.get("lb") is not None and result["lb"]>result["ub"]+TOL:failures.append("LB exceeds UB")
    return evaluation,failures

def oracle_crosscheck(data,weights,direct,evaluation):
    failures=[];details={}
    point={"x":direct["solution"]["x"],"alloc_boxes":direct["solution"]["alloc_boxes"],"eta":evaluation["recourse_cost"]};oracle=GlobalRecourseOracle(data,weights);oracle.update_rhs(point["x"],point["alloc_boxes"]);status=oracle.solve()
    if status!=GRB.OPTIMAL:return [f"oracle status {status}"],details
    value=oracle.objective_value();details["oracle_recourse"]=value
    if abs(value-evaluation["recourse_cost"])>TOL:failures.append("oracle/evaluator recourse mismatch")
    cut=oracle.build_optimality_cut(point,"exact_crosscheck");tight=cut.value_at({**point,"eta":value});details["cut_tightness_error"]=abs(tight)
    if abs(tight)>TOL:failures.append("optimality cut not tight")
    validation=validate_optimality_cut(data,weights,cut,[point],TOL);details["cut_validation"]=validation
    if not validation["valid"]:failures.append("optimality cut validation failed")
    return failures,details

def row(instance_id,digest,method,result,evaluation,status,message=""):
    comp=evaluation or {};feas=comp.get("feasibility",{});parts=comp.get("components",{});main=result.get("phase3_bbc",{}) if method=="full_candidate" else result
    return {"instance":instance_id,"digest":digest,"method":method,"algorithm_status":"provisional" if method=="full_candidate" else "correctness_configuration","status":main.get("status_name",result.get("status_name")),"runtime":result.get("runtime"),"ub":result.get("ub"),"lb":result.get("lb"),"gap":result.get("gap"),"feasible":feas.get("feasible"),"max_violation":feas.get("max_violation"),"objective":comp.get("core_cost"),"open":parts.get("open",{}).get("weighted"),"concentration":parts.get("concentration",{}).get("weighted"),"distance":parts.get("distance",{}).get("weighted"),"balance":parts.get("balance",{}).get("weighted"),"conflict":parts.get("conflict",{}).get("weighted"),"nodes":main.get("nodes"),"cuts":result.get("total_unique_cuts",main.get("new_unique_cuts")),"sp_solves":main.get("sp_statistics",{}).get("sp_solve_count"),"result_status":status,"message":message}

def validate_instance(instance_id,raw,digest,time_limit,threads):
    data=prepare_instance(raw);weights=Weights();failures=[];details={};rows=[]
    direct=solve_direct_gurobi(data,weights,time_limit=time_limit,mip_gap=0,threads=threads,seed=0,concentration_enabled=True);de,errors=check_solution(data,weights,direct,"direct");failures+=errors
    if direct.get("solution"):
        errors,oracle_details=oracle_crosscheck(data,weights,direct,de);failures+=errors;details.update(oracle_details)
    core=solve_bbc_phase(data,weights,time_limit=time_limit,mip_gap=0,threads=threads,seed=0,add_valid_inequalities=False,aggregate_recourse_lb=False,analytic_recourse_lb=False,concentration_enabled=True,cut_strategy="standard",node_cuts=False,warm_start=False,origin_prefix="core_verification");ce,errors=check_solution(data,weights,core,"bbc_core");failures+=errors
    full=solve_true_benders_pipeline(data,weights,total_core_time=time_limit,mip_gap=0,threads=threads,seed=0);best=full.get("core_best",{});full_flat={**full,**best,"status_name":full.get("phase3_bbc",{}).get("status_name")};fe=best.get("components");errors=[]
    if best:_,errors=check_solution(data,weights,full_flat,"full_candidate")
    failures+=errors
    direct_opt=direct.get("status_name")=="OPTIMAL" and direct.get("gap",1)<=TOL;core_opt=core.get("status_name")=="OPTIMAL" and core.get("gap",1)<=TOL
    inconclusive=not (direct_opt and core_opt)
    if direct_opt and core_opt and abs(direct["ub"]-core["ub"])>TOL:failures.append("Direct/BBC core optimal objective mismatch")
    overall="FAIL" if failures else "INCONCLUSIVE" if inconclusive else "PASS";message="; ".join(failures) if failures else "one or both exact methods did not prove optimal" if inconclusive else "all exact checks passed"
    rows.extend([row(instance_id,digest,"direct",direct,de,overall,message),row(instance_id,digest,"bbc_core",core,ce,overall,message),row(instance_id,digest,"full_candidate",full_flat,fe,overall,message)])
    return {"instance_id":instance_id,"digest":digest,"status":overall,"message":message,"direct_optimal":direct_opt,"bbc_core_optimal":core_opt,"objective_difference":None if not(direct.get("ub") is not None and core.get("ub") is not None) else abs(direct["ub"]-core["ub"]),"details":details,"failures":failures},rows

def main():
    p=argparse.ArgumentParser();p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot");p.add_argument("--threads",type=int,default=1);p.add_argument("--time-limit",type=float,default=600);p.add_argument("--output",default="validation/small_exact");a=p.parse_args();out=Path(a.output);(out/"failures").mkdir(parents=True,exist_ok=True);cases=[("tiny",build_builtin_instance("tiny"),instance_digest(build_builtin_instance("tiny"))),("tiny_concentration",build_builtin_instance("tiny_concentration"),instance_digest(build_builtin_instance("tiny_concentration")))]
    manifest=json.loads((Path(a.suite)/"manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["instances"]:
        if entry["size_class"]=="small":
            raw=load_instance(Path(a.suite)/entry["relative_path"]);actual=instance_digest(raw)
            if actual!=entry["digest"]:print(f"FAIL digest {entry['instance_id']}");return 1
            cases.append((entry["instance_id"],raw,actual))
    reports=[];rows=[]
    for instance_id,raw,digest in cases:
        print(f"validating {instance_id} ...",flush=True)
        try:report,new_rows=validate_instance(instance_id,raw,digest,a.time_limit,a.threads)
        except Exception as exc:
            trace=traceback.format_exc();(out/"failures"/f"{instance_id}.txt").write_text(trace,encoding="utf-8");report={"instance_id":instance_id,"digest":digest,"status":"FAIL","message":str(exc),"failures":[str(exc)]};new_rows=[]
        reports.append(report);rows.extend(new_rows);print(f"{instance_id}: {report['status']} - {report['message']}",flush=True)
    result={"protocol":"paper-exp-v1","algorithm_status":"provisional","tolerance":TOL,"time_limit_per_method":a.time_limit,"threads":a.threads,"overall_status":"FAIL" if any(r["status"]=="FAIL" for r in reports) else "INCONCLUSIVE" if any(r["status"]=="INCONCLUSIVE" for r in reports) else "PASS","instances":reports};(out/"report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(out/"results.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with (out/"results.csv").open("w",newline="",encoding="utf-8") as stream:writer=csv.DictWriter(stream,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    lines=["# Small exact crosscheck","",f"Overall: **{result['overall_status']}**","","Current full candidate status: **provisional**.","","| Instance | Status | Direct optimal | BBC core optimal | Message |","|---|---|---:|---:|---|"]+[f"| {r['instance_id']} | {r['status']} | {r.get('direct_optimal')} | {r.get('bbc_core_optimal')} | {r['message']} |" for r in reports];(out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8");return 1 if result["overall_status"]=="FAIL" else 0
if __name__=="__main__":raise SystemExit(main())

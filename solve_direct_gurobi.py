"""Direct monolithic Gurobi baseline for Route-B cross-checks."""
from __future__ import annotations
import argparse,json,os,time
from datetime import datetime
from gurobipy import GRB
from config import MasterWeights,Weights
from data import prepare_instance
from instance_registry import BUILTIN_INSTANCES,list_builtin_instances,resolve_instance
from model_monolithic import build_monolithic_model,extract_solution
from solution_evaluation import evaluate_common_solution
# Backward-compatible read-only-by-convention alias. New code uses instance_registry.
INSTANCES=BUILTIN_INSTANCES
def status_name(s):return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def serial(v):
    if isinstance(v,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):serial(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [serial(x) for x in v]
    return v
def solve_direct_gurobi(data,weights,*,time_limit=30,mip_gap=.03,threads=1,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,seed=0,verbose=False,start_solution=None):
    started=time.perf_counter();deadline=started+max(0,float(time_limit));m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled);build_runtime=time.perf_counter()-started;m.Params.OutputFlag=int(verbose);m.Params.MIPGap=float(mip_gap);m.Params.Threads=int(threads or 1);m.Params.Seed=int(seed)
    if start_solution:
        for name,values in start_solution.items():
            for k,value in values.items():
                if k in v.get(name,{}):v[name][k].Start=value
    remaining=max(0,deadline-time.perf_counter());t=time.perf_counter()
    if remaining>0:m.Params.TimeLimit=remaining;m.optimize()
    optimization_runtime=time.perf_counter()-t;runtime=time.perf_counter()-started;solution=extract_solution(v) if m.SolCount else None;evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled) if solution else None
    if solution and abs(m.ObjVal-evaluation["core_cost"])>1e-5:raise AssertionError("direct objective mismatch")
    ub=evaluation["core_cost"] if evaluation else None;lb=float(m.ObjBound) if remaining>0 and m.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None;return {"ok":solution is not None,"solver_objective":float(m.ObjVal) if solution else None,"status":int(m.Status) if remaining>0 else None,"status_name":status_name(m.Status) if remaining>0 else "DEADLINE_EXHAUSTED","ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"model_build_runtime":build_runtime,"optimization_runtime":optimization_runtime,"runtime":runtime,"nodes":float(m.NodeCount) if remaining>0 else 0.0,"solution":solution,"components":evaluation}

def solve_direct_alns_pipeline(data,weights,*,total_time=180,warm_start_time_share=.15,alns_time_share=.25,mip_gap=.03,threads=1,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,seed=0,lns_options=None):
    """Fair-budget monolithic Gurobi baseline with the same warm/ALNS stages as BBC."""
    from solver_alns import adaptive_lns
    from solver_true_benders import _warm_start
    pipeline_started=time.perf_counter();total=float(total_time);deadline=pipeline_started+total;warm_budget=total*warm_start_time_share;alns_budget=total*alns_time_share;main_budget=total-warm_budget-alns_budget
    if min(warm_budget,alns_budget,main_budget)<0:raise ValueError("direct ALNS time shares exceed total budget")
    warm_limit=min(warm_budget,max(0,deadline-time.perf_counter()));warm_result=_warm_start(data,weights,alloc_domain,warm_limit,add_valid_inequalities,concentration_enabled) if warm_limit>0 else None;warm={"ok":warm_result is not None,"status_name":"WARM_START" if warm_result else "NO_INCUMBENT","ub":None if warm_result is None else warm_result["ub"],"lb":None,"gap":None,"runtime":warm_limit if warm_result is None else warm_result["runtime"],"solution":None if warm_result is None else warm_result["solution"]}
    if warm["ok"]:
        options=dict(lns_options or {});alns=adaptive_lns(data,weights,warm["solution"],time_limit=min(alns_budget,max(0,deadline-time.perf_counter())),alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled,seed=seed,**options);start=alns["best_solution"]
    else:alns={"disabled":True,"reason":"no warm incumbent","start_ub":None,"best_ub":None,"improvement":0.0,"runtime":0.0};start=None
    main_limit=max(0,deadline-time.perf_counter());main=solve_direct_gurobi(data,weights,time_limit=main_limit,mip_gap=mip_gap,threads=threads,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled,seed=seed+1,verbose=False,start_solution=start)
    candidates=[q for q in (warm,main) if q["ok"]]
    if alns.get("best_solution") is not None:
        ae=evaluate_common_solution(data,weights,alns["best_solution"],alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);candidates.append({"ok":True,"ub":ae["core_cost"],"solution":alns["best_solution"],"components":ae,"status_name":"ALNS"})
    best=min(candidates,key=lambda q:q["ub"]) if candidates else main;lb=main.get("lb");ub=best.get("ub")
    return {"ok":bool(candidates),"algorithm":"direct_gurobi_warm_alns","status_name":main["status_name"],"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"runtime":time.perf_counter()-pipeline_started,"nodes":main["nodes"],"solution":best.get("solution"),"components":best.get("components"),"time_budget":{"total":total,"warm":warm_budget,"alns":alns_budget,"main":main_budget,"main_actual_limit":main_limit},"warm_start":{k:warm.get(k) for k in ("ok","status_name","ub","lb","gap","runtime")},"alns":{k:v for k,v in alns.items() if k!="best_solution"},"main_solve":{k:main.get(k) for k in ("ok","status_name","ub","lb","gap","runtime","nodes")}}
def parser():
    p=argparse.ArgumentParser();source=p.add_mutually_exclusive_group();source.add_argument("--instance",choices=list_builtin_instances(),default="3new6old");source.add_argument("--instance-file");p.add_argument("--time",type=float,default=30);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--threads",type=int,default=1);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--concentration",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--concentration-weight",type=float,default=10);p.add_argument("--concentration-mode",choices=("joint-group-bay",),default="joint-group-bay");p.add_argument("--handling-rate-scale",type=float,default=1);p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative"),default="proportional");p.add_argument("--no-valid-inequalities",action="store_true");p.add_argument("--output-root",default="outputs");p.add_argument("--quiet",action="store_true");return p
def main():
    a=parser().parse_args();raw=resolve_instance(builtin_name=None if a.instance_file else a.instance,instance_file=a.instance_file);d=prepare_instance(raw,handling_rate_scale=a.handling_rate_scale,old_outbound_release_policy=a.old_outbound_release_policy);weights=Weights(master=MasterWeights(concentration=a.concentration_weight));r=solve_direct_gurobi(d,weights,time_limit=a.time,mip_gap=a.mip_gap,threads=a.threads,alloc_domain=a.alloc_domain,concentration_enabled=a.concentration,add_valid_inequalities=not a.no_valid_inequalities,verbose=not a.quiet);label=a.instance if not a.instance_file else os.path.splitext(os.path.basename(a.instance_file))[0];out=os.path.join(a.output_root,f"direct_{datetime.now():%Y%m%d_%H%M%S}_{label}");os.makedirs(out,exist_ok=True);json.dump(serial({k:v for k,v in r.items() if k!="solution"}),open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2,default=str);print({k:r[k] for k in ("status_name","ub","lb","gap","runtime")});return 0 if r["ok"] else 2
if __name__=="__main__":raise SystemExit(main())

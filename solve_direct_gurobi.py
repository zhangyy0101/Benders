"""Direct monolithic Gurobi baseline for the current model."""
from __future__ import annotations
import argparse,json,os,time
from datetime import datetime
from gurobipy import GRB
from config import MasterWeights,Weights
from data import list_builtin_instances,prepare_instance,resolve_instance
from model_monolithic import build_monolithic_model,extract_solution
from solution_evaluation import evaluate_common_solution
from anytime import canonicalize

def status_name(s):return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def serial(v):
    if isinstance(v,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):serial(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [serial(x) for x in v]
    return v

def solve_direct_gurobi(data,weights,*,time_limit=30,mip_gap=.03,threads=1,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,seed=0,verbose=False,start_solution=None):
    started=time.perf_counter();deadline=started+max(0,float(time_limit));m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled);build_runtime=time.perf_counter()-started;m.Params.OutputFlag=int(verbose);m.Params.MIPGap=float(mip_gap);m.Params.Threads=int(threads or 1);m.Params.Seed=int(seed);m.Params.IntFeasTol=1e-9
    if start_solution:
        for name,values in start_solution.items():
            for k,value in values.items():
                if k in v.get(name,{}):v[name][k].Start=value
    remaining=max(0,deadline-time.perf_counter());tick=time.perf_counter();events=[];last={"ub":None,"lb":None};incumbents=[0]
    def callback(model,where):
        elapsed=time.perf_counter()-started
        if where==GRB.Callback.MIPSOL:
            ub=float(model.cbGet(GRB.Callback.MIPSOL_OBJ))
            if last["ub"] is None or ub<last["ub"]-1e-7:last["ub"]=ub;events.append({"time":elapsed,"phase":"main","source":"first_incumbent" if incumbents[0]==0 else "incumbent_improvement","ub":ub,"lb":None});incumbents[0]+=1
        elif where==GRB.Callback.MIP:
            lb=float(model.cbGet(GRB.Callback.MIP_OBJBND));threshold=max(1e-6,.001*max(1,abs(last["lb"] or 0)))
            if last["lb"] is None or lb>last["lb"]+threshold:last["lb"]=lb;events.append({"time":elapsed,"phase":"main","source":"bound_improvement","ub":None,"lb":lb})
    if remaining>0:m.Params.TimeLimit=remaining;m.optimize(callback)
    optimization_runtime=time.perf_counter()-tick;runtime=time.perf_counter()-started;solution=extract_solution(v,data) if m.SolCount else None;evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled) if solution else None
    if solution and abs(m.ObjVal-evaluation["core_cost"])>1e-5:raise AssertionError("direct objective mismatch")
    ub=evaluation["core_cost"] if evaluation else None;lb=float(m.ObjBound) if remaining>0 and m.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None
    return {"anytime_trace":canonicalize(events,runtime,ub,lb),"ok":solution is not None,"solver_objective":float(m.ObjVal) if solution else None,"status":int(m.Status) if remaining>0 else None,"status_name":status_name(m.Status) if remaining>0 else "DEADLINE_EXHAUSTED","ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"model_build_runtime":build_runtime,"optimization_runtime":optimization_runtime,"runtime":runtime,"nodes":float(m.NodeCount) if remaining>0 else 0.0,"solution":solution,"components":evaluation}

def parser():
    p=argparse.ArgumentParser();source=p.add_mutually_exclusive_group();source.add_argument("--instance",choices=list_builtin_instances(),default="3new6old");source.add_argument("--instance-file");p.add_argument("--time",type=float,default=30);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--threads",type=int,default=1);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--concentration",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--concentration-weight",type=float,default=10);p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative","ship_complete"),default="ship_complete");p.add_argument("--no-valid-inequalities",action="store_true");p.add_argument("--output-root",default="outputs");p.add_argument("--quiet",action="store_true");return p
def main():
    a=parser().parse_args();raw=resolve_instance(builtin_name=None if a.instance_file else a.instance,instance_file=a.instance_file);d=prepare_instance(raw,old_outbound_release_policy=a.old_outbound_release_policy);weights=Weights(master=MasterWeights(concentration=a.concentration_weight));r=solve_direct_gurobi(d,weights,time_limit=a.time,mip_gap=a.mip_gap,threads=a.threads,alloc_domain=a.alloc_domain,concentration_enabled=a.concentration,add_valid_inequalities=not a.no_valid_inequalities,verbose=not a.quiet);label=a.instance if not a.instance_file else os.path.splitext(os.path.basename(a.instance_file))[0];out=os.path.join(a.output_root,f"direct_{datetime.now():%Y%m%d_%H%M%S}_{label}");os.makedirs(out,exist_ok=True);json.dump(serial({k:v for k,v in r.items() if k!="solution"}),open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2,default=str);print({k:r[k] for k in ("status_name","ub","lb","gap","runtime")});return 0 if r["ok"] else 2
if __name__=="__main__":raise SystemExit(main())

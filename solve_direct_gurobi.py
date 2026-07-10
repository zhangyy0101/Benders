"""Plain monolithic Gurobi baseline using exactly the Route-A core builder."""
from __future__ import annotations
import argparse,json,os,time
from datetime import datetime
from gurobipy import GRB
from config import Weights
from data import (prepare_instance,get_data_3new6old_fixed,get_data_tiny_route_a,get_data_baptbi_5n_4b_4p,get_data_baptbi_8n_4b_4p,get_data_baptbi_10n_4b_4p,get_data_baptbi_15n_4b_5p,get_data_baptbi_25n_6b_5p,get_data_barcelona_bcn36a_5n,get_data_barcelona_bcn36a_8n,get_data_barcelona_bcn36a_10n,get_data_barcelona_bcn36a_20n)
from model_core import build_core_monolithic_model,evaluate_core_solution,extract_solution

INSTANCES={"tiny":get_data_tiny_route_a,"3new6old":get_data_3new6old_fixed,"baptbi_5n_4b_4p":get_data_baptbi_5n_4b_4p,"baptbi_8n_4b_4p":get_data_baptbi_8n_4b_4p,"baptbi_10n_4b_4p":get_data_baptbi_10n_4b_4p,"baptbi_15n_4b_5p":get_data_baptbi_15n_4b_5p,"baptbi_25n_6b_5p":get_data_baptbi_25n_6b_5p,"barcelona_bcn36a_5n":get_data_barcelona_bcn36a_5n,"barcelona_bcn36a_8n":get_data_barcelona_bcn36a_8n,"barcelona_bcn36a_10n":get_data_barcelona_bcn36a_10n,"barcelona_bcn36a_20n":get_data_barcelona_bcn36a_20n}
def _jsonable(value):
    if isinstance(value,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):_jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_jsonable(v) for v in value]
    return value
def _status(s): return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.INTERRUPTED:"INTERRUPTED",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def _decode_solution(path):
    if not path:return None
    raw=json.load(open(path,encoding="utf8")); return {name:{tuple(int(x) if x.lstrip('-').isdigit() else x for x in key.split('|')):value for key,value in values.items()} for name,values in raw.items()}
def solve_direct_gurobi(data,weights,*,time_limit_s=None,mip_gap=.05,threads=None,method=None,node_method=None,mip_focus=None,heuristics=None,no_rel_heur_time=None,cuts=None,presolve=None,verbose=True,alloc_domain="integer",add_valid_inequalities=True,start_solution=None):
    model,variables,expr=build_core_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities); model.ModelName="plain_monolithic_gurobi_baseline"; model.Params.OutputFlag=int(verbose); model.Params.MIPGap=float(mip_gap)
    for parameter,value in (("TimeLimit",time_limit_s),("Threads",threads),("Method",method),("NodeMethod",node_method),("MIPFocus",mip_focus),("Heuristics",heuristics),("NoRelHeurTime",no_rel_heur_time),("Cuts",cuts),("Presolve",presolve)):
        if value is not None:setattr(model.Params,parameter,value)
    if start_solution:
        for name,values in start_solution.items():
            for key,value in values.items():
                if key in variables.get(name,{}):variables[name][key].Start=value
    t=time.perf_counter(); model.optimize(); runtime=time.perf_counter()-t; has=model.SolCount>0; solution=extract_solution(expr["data"],variables) if has else None; evaluation=evaluate_core_solution(expr["data"],weights,solution) if has else None
    if has and abs(model.ObjVal-evaluation["total_core_cost"])>1e-5:raise AssertionError("direct objective mismatch")
    lb=float(model.ObjBound) if model.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None; ub=evaluation["total_core_cost"] if evaluation else None
    return {"ok":has,"status":int(model.Status),"status_name":_status(model.Status),"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"runtime":runtime,"nodes":float(model.NodeCount),"root_bound":lb if float(model.NodeCount)<=1 else None,"solution_count":int(model.SolCount),"num_vars":model.NumVars,"num_constrs":model.NumConstrs,"components":evaluation,"solution":solution}
def main():
    p=argparse.ArgumentParser(description="Plain monolithic Gurobi baseline"); p.add_argument("--instance",choices=INSTANCES,default="3new6old"); p.add_argument("--time",type=float); p.add_argument("--mip-gap",type=float,default=.05); p.add_argument("--threads",type=int); p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer"); p.add_argument("--handling-rate-scale",type=float,default=1); p.add_argument("--no-valid-inequalities",action="store_true"); p.add_argument("--start-solution"); p.add_argument("--output-root",default="outputs"); p.add_argument("--quiet",action="store_true"); a=p.parse_args(); data=prepare_instance(INSTANCES[a.instance](),a.handling_rate_scale); result=solve_direct_gurobi(data,Weights(),time_limit_s=a.time,mip_gap=a.mip_gap,threads=a.threads,verbose=not a.quiet,alloc_domain=a.alloc_domain,add_valid_inequalities=not a.no_valid_inequalities,start_solution=_decode_solution(a.start_solution)); result["instance"]=a.instance
    out=os.path.abspath(os.path.join(a.output_root,f"direct_{datetime.now():%Y%m%d_%H%M%S}_{a.instance}")); os.makedirs(out,exist_ok=True); serial=_jsonable({k:v for k,v in result.items() if k!="solution"}); json.dump(serial,open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2); print(json.dumps({k:serial[k] for k in ("status_name","ub","lb","gap","runtime")},indent=2)); return 0 if result["ok"] else 2
if __name__=="__main__":raise SystemExit(main())

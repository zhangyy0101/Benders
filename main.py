"""Route-B True Branch-and-Benders-Cut pipeline CLI."""
from __future__ import annotations
import argparse,json,os
from datetime import datetime
from config import Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES
from solver_true_benders import solve_true_benders_pipeline
def serial(v):
    if isinstance(v,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):serial(x) for k,x in v.items() if k not in {"cut_pool"}}
    if isinstance(v,(list,tuple)):return [serial(x) for x in v]
    return v
def main():
    p=argparse.ArgumentParser(description="True BBC + ALNS + epsilon attribute refinement");p.add_argument("--instance",choices=INSTANCES,default="3new6old");p.add_argument("--phase1-time",type=float,default=20);p.add_argument("--lns-time",type=float,default=20);p.add_argument("--phase3-time",type=float,default=20);p.add_argument("--root-cut-prepass",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--root-cut-max-iters",type=int,default=20);p.add_argument("--root-cut-time",type=float,default=10);p.add_argument("--node-cut-limit",type=int,default=100);p.add_argument("--no-node-cuts",action="store_true");p.add_argument("--no-valid-inequalities",action="store_true");p.add_argument("--no-alns",action="store_true");p.add_argument("--no-warm-start",action="store_true");p.add_argument("--attribute-epsilon",type=float,default=.01);p.add_argument("--attribute-time",type=float,default=10);p.add_argument("--attribute-scope",choices=("final","horizon"),default="final");p.add_argument("--no-attribute-refinement",action="store_true");p.add_argument("--handling-rate-scale",type=float,default=1);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--threads",type=int,default=1);p.add_argument("--seed",type=int,default=0);p.add_argument("--output-root",default="outputs");a=p.parse_args();data=prepare_instance(INSTANCES[a.instance](),a.handling_rate_scale);r=solve_true_benders_pipeline(data,Weights(),phase1_time=a.phase1_time,lns_time=a.lns_time,phase3_time=a.phase3_time,attribute_time=a.attribute_time,mip_gap=a.mip_gap,alloc_domain=a.alloc_domain,add_valid_inequalities=not a.no_valid_inequalities,root_prepass=a.root_cut_prepass,root_cut_max_iters=a.root_cut_max_iters,root_cut_time=a.root_cut_time,node_cuts=not a.no_node_cuts,node_cut_limit=a.node_cut_limit,enable_alns=not a.no_alns,enable_refinement=not a.no_attribute_refinement,attribute_epsilon=a.attribute_epsilon,attribute_scope=a.attribute_scope,seed=a.seed,threads=a.threads,warm_start=not a.no_warm_start);out=os.path.abspath(os.path.join(a.output_root,f"true_bbc_{datetime.now():%Y%m%d_%H%M%S}_{a.instance}"));os.makedirs(out,exist_ok=True)
    if r.get("ok"):
        json.dump(serial(r["core_best"]["solution"]),open(os.path.join(out,"core_best_solution.json"),"w",encoding="utf8"),indent=2);json.dump(serial(r["attribute_refinement"]["solution"]),open(os.path.join(out,"attribute_refined_solution.json"),"w",encoding="utf8"),indent=2);r["core_best"]["solution_file"]="core_best_solution.json";r["attribute_refinement"]["solution_file"]="attribute_refined_solution.json"
    json.dump(serial(r),open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2,default=str)
    if r.get("ok"):
        c=r["core_best"];p1=r["phase1_bbc"];p3=r["phase3_bbc"];print(f"Core UB/LB/gap: {c['ub']:.6f} / {c['lb']:.6f} / {c['gap']:.6f}");print(f"Phase1 cuts opt/feas: {p1['cut_statistics']['incumbent_optimality_cuts']+p1['cut_statistics']['node_optimality_cuts']} / {p1['cut_statistics']['incumbent_feasibility_cuts']+p1['cut_statistics']['node_feasibility_cuts']}");print(f"Phase3 inherited/new: {r['cuts_inherited_by_phase3']} / {r['new_phase3_cuts']}");print(f"SP solves: {p1['sp_statistics']['sp_solve_count']+p3['sp_statistics']['sp_solve_count']}")
    else:print("No exact recourse-feasible incumbent")
    print(f"Summary: {os.path.join(out,'summary.json')}");return 0 if r.get("ok") else 2
if __name__=="__main__":raise SystemExit(main())

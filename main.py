"""Route-B strengthened true Branch-and-Benders-Cut command line interface."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime
from config import Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES
from solver_true_benders import solve_true_benders_pipeline

def serial(v):
    if isinstance(v,dict): return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):serial(x) for k,x in v.items() if k!="cut_pool"}
    if isinstance(v,(list,tuple)): return [serial(x) for x in v]
    return v

def parser():
    p=argparse.ArgumentParser(description="Strengthened true BBC + adaptive LNS + attribute refinement")
    p.add_argument("--instance",choices=INSTANCES,default="3new6old");p.add_argument("--total-core-time",type=float,default=60)
    p.add_argument("--root-time-share",type=float,default=.20);p.add_argument("--warm-start-time-share",type=float,default=.05);p.add_argument("--alns-time-share",type=float,default=.15);p.add_argument("--main-bbc-time-share",type=float,default=.60)
    p.add_argument("--root-cut-prepass",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--root-cut-max-iters",type=int,default=100);p.add_argument("--root-cut-time",type=float);p.add_argument("--root-cut-relative-improvement-tol",type=float,default=1e-4);p.add_argument("--root-cut-violation-tol",type=float,default=1e-6);p.add_argument("--root-cut-stall-iters",type=int,default=5)
    p.add_argument("--aggregate-recourse-lb",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--analytic-recourse-lb",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--cut-strategy",choices=("standard","stabilized"),default="standard")
    p.add_argument("--node-cuts",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--node-cut-limit",type=int,default=100);p.add_argument("--node-separation-policy",choices=("root-only","periodic","adaptive"),default="root-only");p.add_argument("--node-separation-interval",type=int,default=20);p.add_argument("--callback-time-share-limit",type=float,default=.4)
    p.add_argument("--valid-inequalities",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--alns",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--warm-start",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--attribute-refinement",action=argparse.BooleanOptionalAction,default=True)
    p.add_argument("--lns-repair-time",type=float,default=2);p.add_argument("--lns-min-destroy",type=float,default=.1);p.add_argument("--lns-max-destroy",type=float,default=.35);p.add_argument("--lns-restarts",type=int,default=1);p.add_argument("--lns-stall-iters",type=int,default=10)
    p.add_argument("--attribute-epsilon",type=float,default=.01);p.add_argument("--attribute-time",type=float,default=10);p.add_argument("--attribute-scope",choices=("final","horizon"),default="final")
    p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative"),default="proportional");p.add_argument("--handling-rate-scale",type=float,default=1);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--numeric-focus",type=int,choices=range(4),default=1);p.add_argument("--threads",type=int,default=1);p.add_argument("--seed",type=int,default=0);p.add_argument("--output-root",default="outputs")
    return p

def main():
    a=parser().parse_args();data=prepare_instance(INSTANCES[a.instance](),a.handling_rate_scale,a.old_outbound_release_policy)
    lns={"repair_time":a.lns_repair_time,"min_destroy":a.lns_min_destroy,"max_destroy":a.lns_max_destroy,"restarts":a.lns_restarts,"stall_iters":a.lns_stall_iters}
    r=solve_true_benders_pipeline(data,Weights(),total_core_time=a.total_core_time,root_time_share=a.root_time_share,warm_start_time_share=a.warm_start_time_share,alns_time_share=a.alns_time_share,main_bbc_time_share=a.main_bbc_time_share,attribute_time=a.attribute_time,mip_gap=a.mip_gap,alloc_domain=a.alloc_domain,add_valid_inequalities=a.valid_inequalities,aggregate_recourse_lb=a.aggregate_recourse_lb,analytic_recourse_lb=a.analytic_recourse_lb,cut_strategy=a.cut_strategy,root_prepass=a.root_cut_prepass,root_cut_max_iters=a.root_cut_max_iters,root_cut_time=a.root_cut_time,root_cut_relative_improvement_tol=a.root_cut_relative_improvement_tol,root_cut_violation_tol=a.root_cut_violation_tol,root_cut_stall_iters=a.root_cut_stall_iters,node_cuts=a.node_cuts,node_cut_limit=a.node_cut_limit,node_separation_policy=a.node_separation_policy,node_separation_interval=a.node_separation_interval,callback_time_share_limit=a.callback_time_share_limit,enable_alns=a.alns,enable_refinement=a.attribute_refinement,attribute_epsilon=a.attribute_epsilon,attribute_scope=a.attribute_scope,seed=a.seed,threads=a.threads,warm_start=a.warm_start,numeric_focus=a.numeric_focus,lns_options=lns)
    out=os.path.abspath(os.path.join(a.output_root,f"true_bbc_{datetime.now():%Y%m%d_%H%M%S}_{a.instance}"));os.makedirs(out,exist_ok=True)
    if r.get("ok"):
        json.dump(serial(r["core_best"]["solution"]),open(os.path.join(out,"core_best_solution.json"),"w",encoding="utf8"),indent=2);r["core_best"]["solution_file"]="core_best_solution.json"
        if r["attribute_refinement"].get("solution") is not None: json.dump(serial(r["attribute_refinement"]["solution"]),open(os.path.join(out,"attribute_refined_solution.json"),"w",encoding="utf8"),indent=2);r["attribute_refinement"]["solution_file"]="attribute_refined_solution.json"
    json.dump(serial(r),open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2,default=str)
    if r.get("ok"):
        c=r["core_best"];root=r["phase0_root_prepass"];main=r["phase3_bbc"];print(f"Core UB/LB/gap: {c['ub']:.6f} / {c['lb']:.6f} / {c['gap']:.6f}");print(f"Root open/eta/aggregate: {root.get('master_open_bound')} / {root.get('master_eta_bound')} / {root.get('aggregate_recourse_bound')}");print(f"Unique cuts / SP solves: {r['total_unique_cuts']} / {main.get('sp_statistics',{}).get('sp_solve_count',0)}")
    else: print("No exact recourse-feasible incumbent")
    print(f"Summary: {os.path.join(out,'summary.json')}");return 0 if r.get("ok") else 2
if __name__=="__main__": raise SystemExit(main())

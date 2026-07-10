"""CLI for strengthened monolithic MIP, adaptive LNS and attribute refinement."""
from __future__ import annotations
import argparse,json,os,platform,sys
from datetime import datetime
import gurobipy as gp
from config import AttributeRefinementWeights,Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES
from solver_mip_alns import solve_strengthened_mip_alns

def _jsonable(value):
    if isinstance(value,dict):return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):_jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_jsonable(v) for v in value]
    return value
def _without(d,*keys):return {k:v for k,v in d.items() if k not in set(keys)}
def parser():
    p=argparse.ArgumentParser(description="Strengthened MIP + adaptive LNS + epsilon-constrained attribute refinement")
    p.add_argument("--instance",choices=INSTANCES,default="3new6old");p.add_argument("--phase1-time",type=float,default=20);p.add_argument("--lns-time",type=float,default=45);p.add_argument("--phase3-time",type=float,default=20);p.add_argument("--attribute-time",type=float,default=20);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--threads",type=int);p.add_argument("--attribute-epsilon",type=float,default=.01);p.add_argument("--attribute-scope",choices=("final","horizon"),default="final");p.add_argument("--attribute-basis",choices=("inventory","reservation"),default="inventory");p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--handling-rate-scale",type=float,default=1);p.add_argument("--old-outbound-release-policy",choices=("legacy_sorted","conservative","proportional"),default="proportional");p.add_argument("--symmetry-breaking",choices=("on","off"),default="off");p.add_argument("--no-valid-inequalities",action="store_true");p.add_argument("--no-alns",action="store_true");p.add_argument("--no-proof",action="store_true");p.add_argument("--no-attribute-refinement",action="store_true");p.add_argument("--attribute-components",choices=("all","pod","weight","height"),default="all");p.add_argument("--seed",type=int,default=0);p.add_argument("--output-root",default="outputs");p.add_argument("--verbose",action="store_true")
    p.add_argument("--lns-repair-time",type=float,default=5);p.add_argument("--lns-repair-gap",type=float,default=.03);p.add_argument("--lns-min-destroy",type=float,default=.10);p.add_argument("--lns-max-destroy",type=float,default=.35);p.add_argument("--lns-stall-iters",type=int,default=10);p.add_argument("--lns-min-iters",type=int,default=1);p.add_argument("--lns-restarts",type=int,default=1);p.add_argument("--lns-temperature",type=float,default=.02);p.add_argument("--lns-cooling-rate",type=float,default=.98);return p
def main():
    a=parser().parse_args();aw=AttributeRefinementWeights(4 if a.attribute_components in ("all","pod") else 0,3 if a.attribute_components in ("all","weight") else 0,10 if a.attribute_components in ("all","height") else 0);weights=Weights(attribute=aw);data=prepare_instance(INSTANCES[a.instance](),a.handling_rate_scale,a.old_outbound_release_policy)
    lns={"repair_time_s":a.lns_repair_time,"repair_gap":a.lns_repair_gap,"min_destroy":a.lns_min_destroy,"max_destroy":a.lns_max_destroy,"stall_iters":a.lns_stall_iters,"min_iters":a.lns_min_iters,"restarts":a.lns_restarts,"temperature":a.lns_temperature,"cooling_rate":a.lns_cooling_rate}
    r=solve_strengthened_mip_alns(data,weights,phase1_time=a.phase1_time,lns_time=a.lns_time,phase3_time=a.phase3_time,attribute_time=a.attribute_time,attribute_epsilon=a.attribute_epsilon,attribute_scope=a.attribute_scope,attribute_basis=a.attribute_basis,alloc_domain=a.alloc_domain,add_valid_inequalities=not a.no_valid_inequalities,symmetry_breaking=a.symmetry_breaking=="on",seed=a.seed,threads=a.threads,mip_gap=a.mip_gap,verbose=a.verbose,enable_alns=not a.no_alns,enable_proof=not a.no_proof,enable_refinement=not a.no_attribute_refinement,lns_options=lns)
    out=os.path.abspath(os.path.join(a.output_root,f"route_a_{datetime.now():%Y%m%d_%H%M%S}_{a.instance}"));os.makedirs(out,exist_ok=True)
    settings={"alloc_domain":a.alloc_domain,"handling_rate_base":data["handling_rate_base"],"handling_rate_scale":a.handling_rate_scale,"handling_rate_source":data["handling_rate_source"],"valid_inequalities":not a.no_valid_inequalities,"symmetry_breaking":a.symmetry_breaking=="on","attribute_basis":a.attribute_basis,"attribute_scope":a.attribute_scope,"attribute_data_available":r.get("attribute_data_available",False),"old_outbound_release_policy":a.old_outbound_release_policy,"seed":a.seed,"threads":a.threads,"mip_gap":a.mip_gap,"python_version":sys.version.split()[0],"gurobi_version":".".join(map(str,gp.gurobi.version())),"machine":platform.platform()}
    if r.get("ok"):
        core,ref,final=r["core_best"],r["attribute_refinement"],r["final_solution"]
        for filename,solution in (("core_best_solution.json",core["solution"]),("attribute_refined_solution.json",ref["solution"])):
            json.dump(_jsonable(solution),open(os.path.join(out,filename),"w",encoding="utf8"),indent=2)
        json.dump(_jsonable(r["phase2_alns"].get("iterations",[])),open(os.path.join(out,"alns_iterations.json"),"w",encoding="utf8"),indent=2)
        summary={"algorithm":"strengthened_mip_alns","instance":a.instance,"settings":settings,"phase1_core_mip":_without(r["phase1_core_mip"],"solution"),"phase2_alns":{**_without(r["phase2_alns"],"best_solution","iterations"),"iteration_count":len(r["phase2_alns"].get("iterations",[])),"iterations_file":"alns_iterations.json"},"phase3_proof_mip":_without(r["phase3_proof_mip"],"solution"),"core_best":{**_without(core,"solution"),"solution_file":"core_best_solution.json"},"attribute_refinement":{**_without(ref,"solution"),"solution_file":"attribute_refined_solution.json"},"final_solution":{"solution_source":final["solution_source"],"components":final["components"],"solution_file":"attribute_refined_solution.json" if ref["accepted"] else "core_best_solution.json"}}
    else:summary={"algorithm":"strengthened_mip_alns","instance":a.instance,"settings":settings,"status":"no_valid_phase1_incumbent","phase1_core_mip":_without(r["phase1_core_mip"],"solution")}
    json.dump(_jsonable(summary),open(os.path.join(out,"summary.json"),"w",encoding="utf8"),indent=2)
    print("Core best solution")
    if r.get("ok"):
        print(f"  source {core['solution_source']}\n  UB {core['ub']:.6f}\n  LB {core['lb']}\n  gap {core['gap']}\n  max violation {core['feasibility_report']['max_violation']}");print("Attribute-refined solution");print(f"  status {ref['status']}\n  basis/scope {a.attribute_basis}/{a.attribute_scope}\n  score {ref['start_attribute_score']} -> {ref['candidate_attribute_score']}\n  degradation {ref['core_degradation_absolute']} ({None if ref['core_degradation_relative'] is None else 100*ref['core_degradation_relative']}%)")
    else:print("  no independently validated incumbent")
    print(f"Summary: {os.path.join(out,'summary.json')}");return 0 if r.get("ok") else 2
if __name__=="__main__":raise SystemExit(main())

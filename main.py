"""Command-line entry point for the Route-A strengthened MIP--ALNS pipeline."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime
from config import Weights
from data import prepare_instance
from solve_direct_gurobi import INSTANCES
from solver_mip_alns import solve_strengthened_mip_alns

def _jsonable(value):
    if isinstance(value, dict): return {("|".join(map(str,k)) if isinstance(k,tuple) else str(k)):_jsonable(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [_jsonable(v) for v in value]
    return value

def _phase_summary(p): return {k:v for k,v in p.items() if k not in {"solution","components","iterations","operators","best_solution"}}

def main():
    parser=argparse.ArgumentParser(description="Strengthened MIP + adaptive LNS + epsilon-constrained attribute refinement")
    parser.add_argument("--instance",choices=INSTANCES,default="3new6old"); parser.add_argument("--phase1-time",type=float,default=20); parser.add_argument("--lns-time",type=float,default=45); parser.add_argument("--phase3-time",type=float,default=20); parser.add_argument("--attribute-time",type=float,default=20); parser.add_argument("--attribute-epsilon",type=float,default=.01); parser.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer"); parser.add_argument("--handling-rate-scale",type=float,default=1.0); parser.add_argument("--no-valid-inequalities",action="store_true"); parser.add_argument("--seed",type=int,default=0); parser.add_argument("--output-root",default="outputs"); parser.add_argument("--verbose",action="store_true"); args=parser.parse_args()
    data=prepare_instance(INSTANCES[args.instance](),args.handling_rate_scale); result=solve_strengthened_mip_alns(data,Weights(),phase1_time=args.phase1_time,lns_time=args.lns_time,phase3_time=args.phase3_time,attribute_time=args.attribute_time,attribute_epsilon=args.attribute_epsilon,alloc_domain=args.alloc_domain,add_valid_inequalities=not args.no_valid_inequalities,seed=args.seed,verbose=args.verbose)
    out=os.path.abspath(os.path.join(args.output_root,f"route_a_{datetime.now():%Y%m%d_%H%M%S}_{args.instance}")); os.makedirs(out,exist_ok=True)
    if result.get("ok"):
        core=result["core_best"]; ref=result["attribute_refinement"]
        with open(os.path.join(out,"core_best_solution.json"),"w",encoding="utf8") as f: json.dump(_jsonable(core["solution"]),f,indent=2)
        with open(os.path.join(out,"attribute_refined_solution.json"),"w",encoding="utf8") as f: json.dump(_jsonable(ref["solution"]),f,indent=2)
        summary={"algorithm":"strengthened_mip_alns","instance":args.instance,"settings":{"alloc_domain":args.alloc_domain,"handling_rate_base":data["handling_rate_base"],"handling_rate_scale":args.handling_rate_scale,"handling_rate_source":data["handling_rate_source"],"valid_inequalities":not args.no_valid_inequalities},"phase1_core_mip":_phase_summary(result["phase1_core_mip"]),"phase2_alns":_phase_summary(result["phase2_alns"]),"phase3_proof_mip":_phase_summary(result["phase3_proof_mip"]),"core_best":{"ub":core["ub"],"lb":core["lb"],"gap":core["gap"],"solution_file":"core_best_solution.json"},"attribute_refinement":{**{k:v for k,v in ref.items() if k!="solution"},"solution_file":"attribute_refined_solution.json"}}
    else: summary={"algorithm":"strengthened_mip_alns","instance":args.instance,"status":"no_phase1_incumbent","phase1_core_mip":_phase_summary(result["phase1_core_mip"])}
    with open(os.path.join(out,"summary.json"),"w",encoding="utf8") as f: json.dump(_jsonable(summary),f,indent=2)
    print("Core best solution")
    if result.get("ok"):
        print(f"  UB {core['ub']:.6f}\n  LB {core['lb']}\n  gap {core['gap']}"); print("Attribute-refined solution"); print(f"  accepted {ref['accepted']}\n  core cost {ref['candidate_core_cost']}\n  core degradation {ref['core_degradation']}\n  attribute score before/after {ref['start_attribute_score']} / {ref['candidate_attribute_score']}")
    else: print("  no incumbent")
    print(f"Summary: {os.path.join(out,'summary.json')}"); return 0 if result.get("ok") else 2

if __name__=="__main__": raise SystemExit(main())

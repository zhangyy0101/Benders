"""Single-instance CLI for the current partial branch-and-Benders-cut solver."""
from __future__ import annotations
import argparse,json,os
from datetime import datetime
from config import MasterWeights,Weights
from data import list_builtin_instances,prepare_instance,resolve_instance
from solver_partial_bbc import solve_partial_bbc

def serial(value):
    if isinstance(value,dict):return {("|".join(map(str,key)) if isinstance(key,tuple) else str(key)):serial(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [serial(item) for item in value]
    return value

def parser():
    p=argparse.ArgumentParser(description="Current POD/size/height partial BBC solver");source=p.add_mutually_exclusive_group();source.add_argument("--instance",choices=list_builtin_instances(),default="3new6old");source.add_argument("--instance-file");p.add_argument("--time",type=float,default=60);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--threads",type=int,default=1);p.add_argument("--seed",type=int,default=0);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--concentration",action=argparse.BooleanOptionalAction,default=True);p.add_argument("--concentration-weight",type=float,default=10);p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative","ship_complete"),default="ship_complete");p.add_argument("--output-root",default="outputs");return p

def main():
    a=parser().parse_args();raw=resolve_instance(builtin_name=None if a.instance_file else a.instance,instance_file=a.instance_file);data=prepare_instance(raw,old_outbound_release_policy=a.old_outbound_release_policy);weights=Weights(master=MasterWeights(concentration=a.concentration_weight));result=solve_partial_bbc(data,weights,time_limit=a.time,mip_gap=a.mip_gap,threads=a.threads,seed=a.seed,alloc_domain=a.alloc_domain,concentration_enabled=a.concentration);label=a.instance if not a.instance_file else os.path.splitext(os.path.basename(a.instance_file))[0];out=os.path.abspath(os.path.join(a.output_root,f"partial_bbc_{datetime.now():%Y%m%d_%H%M%S}_{label}"));os.makedirs(out,exist_ok=True);solution=result.pop("solution",None)
    if solution is not None:
        with open(os.path.join(out,"solution.json"),"w",encoding="utf8") as handle:json.dump(serial(solution),handle,indent=2)
        result["solution_file"]="solution.json"
    with open(os.path.join(out,"summary.json"),"w",encoding="utf8") as handle:json.dump(serial(result),handle,indent=2,default=str)
    print({key:result.get(key) for key in ("status_name","ub","lb","gap","runtime")});print(f"Summary: {os.path.join(out,'summary.json')}");return 0 if result.get("ok") else 2

if __name__=="__main__":raise SystemExit(main())

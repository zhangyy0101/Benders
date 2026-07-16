"""Minimal batch comparison runner for the retained nine-instance suite."""
from __future__ import annotations
import argparse,csv,json
from pathlib import Path
from benchmark_io import load_instance
from config import Weights
from data import prepare_instance
from solve_direct_gurobi import solve_direct_gurobi
from solver_classical_benders import solve_classical_benders
from solver_partial_bbc import solve_partial_bbc

METHODS={"direct":solve_direct_gurobi,"bbc_candidate":solve_partial_bbc,"classical_benders":solve_classical_benders}

def serial(value):
    if isinstance(value,dict):return {("|".join(map(str,key)) if isinstance(key,tuple) else str(key)):serial(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [serial(item) for item in value]
    return value

def parser():
    p=argparse.ArgumentParser(description="Compare exact methods on the current suite");p.add_argument("--suite-dir",default="benchmarks/paper_exp_v1_pilot21");p.add_argument("--instances",nargs="+");p.add_argument("--methods",nargs="+",choices=tuple(METHODS),default=["direct","bbc_candidate"]);p.add_argument("--budget",type=float,default=60);p.add_argument("--threads",type=int,default=1);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--seed",type=int,default=0);p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative","ship_complete"),default="ship_complete");p.add_argument("--output",default="results");return p

def main():
    a=parser().parse_args();root=Path(a.suite_dir);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));wanted=set(a.instances or [row["instance_id"] for row in manifest["instances"]]);entries=[row for row in manifest["instances"] if row["instance_id"] in wanted];missing=wanted-{row["instance_id"] for row in entries}
    if missing:raise ValueError(f"unknown instances: {sorted(missing)}")
    rows=[]
    for entry in entries:
        data=prepare_instance(load_instance(root/entry["relative_path"]),old_outbound_release_policy=a.old_outbound_release_policy)
        for method in a.methods:
            result=METHODS[method](data,Weights(),time_limit=a.budget,mip_gap=a.mip_gap,threads=a.threads,seed=a.seed);rows.append({"instance":entry["instance_id"],"method":method,"status":result.get("status_name"),"ub":result.get("ub"),"lb":result.get("lb"),"gap":result.get("gap"),"runtime":result.get("runtime"),"nodes":result.get("nodes"),"details":serial({k:v for k,v in result.items() if k not in ("solution","components")})});print(entry["instance_id"],method,result.get("status_name"),result.get("gap"),flush=True)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True);(out/"results.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with (out/"results.csv").open("w",newline="",encoding="utf-8-sig") as handle:
        writer=csv.DictWriter(handle,fieldnames=("instance","method","status","ub","lb","gap","runtime","nodes"));writer.writeheader();writer.writerows({k:r[k] for k in writer.fieldnames} for r in rows)
    return 0

if __name__=="__main__":raise SystemExit(main())

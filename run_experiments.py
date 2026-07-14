"""CLI for configuration-aware, recoverable paper experiment runs."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from algorithm_configuration import configuration_hash
from algorithm_configurations import get_algorithm_configuration,list_algorithm_configurations
from benchmark_io import instance_digest,load_instance
from experiment_methods import METHODS
from experiment_runner import run_jobs

def parser(*, include_historical=False):
    p=argparse.ArgumentParser(description="Generic/legacy multi-method runner; candidate runs must use scripts/run_candidate_experiments.py");p.add_argument("--suite-dir",default="benchmarks/paper_exp_v1_pilot21");p.add_argument("--instances",nargs="+");p.add_argument("--methods",nargs="+",choices=METHODS,default=["direct","bbc_candidate"]);p.add_argument("--include-historical-configs",action="store_true",help="show and allow archived development configurations");p.add_argument("--algorithm-configs",nargs="+",choices=list_algorithm_configurations(include_historical=include_historical),default=["algorithm-candidate-v1"]);p.add_argument("--seeds",nargs="+",type=int,default=[0]);p.add_argument("--budget",type=float,default=300);p.add_argument("--threads",type=int,default=1);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--alloc-domain",choices=("integer","continuous"),default="integer");p.add_argument("--handling-rate-scale",type=float,default=1.0);p.add_argument("--old-outbound-release-policy",choices=("proportional","legacy_sorted","conservative"),default="proportional");p.add_argument("--output",default="experiments/pilot21_runs");p.add_argument("--resume",action="store_true");p.add_argument("--rerun-failed",action="store_true");p.add_argument("--save-solutions",action="store_true");return p
def _simple_configuration(method):
    value={"algorithm_family":method,"configuration_name":f"{method}_baseline","configuration_version":"1","status":"baseline"};value["configuration_hash"]=configuration_hash(value);return value
def build_jobs(args):
    root=Path(args.suite_dir);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));wanted=set(args.instances or [row["instance_id"] for row in manifest["instances"]]);entries=[row for row in manifest["instances"] if row["instance_id"] in wanted]
    missing=wanted-{row["instance_id"] for row in entries}
    if missing:raise ValueError(f"unknown suite instances: {sorted(missing)}")
    jobs=[]
    for row in entries:
        path=root/row["relative_path"];actual=instance_digest(load_instance(path))
        if actual!=row["digest"]:raise ValueError(f"fatal digest mismatch for {row['instance_id']}")
        for method in args.methods:
            configs=[get_algorithm_configuration(name) for name in args.algorithm_configs] if method=="bbc_candidate" else [get_algorithm_configuration("bbc_core") if method=="bbc_core_verification" else _simple_configuration(method)]
            for config in configs:
                for seed in args.seeds:jobs.append({"instance_id":row["instance_id"],"instance_path":path,"expected_digest":actual,"method":method,"configuration":config,"seed":seed,"budget":args.budget,"threads":args.threads,"mip_gap":args.mip_gap,"alloc_domain":args.alloc_domain,"handling_rate_scale":args.handling_rate_scale,"outbound_policy":args.old_outbound_release_policy})
    return jobs
def main():
    include_historical="--include-historical-configs" in sys.argv[1:];args=parser(include_historical=include_historical).parse_args();print("WARNING: run_experiments.py is generic/legacy; use scripts/run_candidate_experiments.py for candidate evidence",file=sys.stderr);jobs=build_jobs(args);rows=run_jobs(jobs,args.output,resume=args.resume,rerun_failed=args.rerun_failed,save_solutions=args.save_solutions,command=" ".join(sys.argv));print(f"results: {len(rows)} total rows, {len(jobs)} requested jobs");return 0
if __name__=="__main__":raise SystemExit(main())

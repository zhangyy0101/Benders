from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from algorithm_configuration import configuration_hash
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest,load_instance
from experiment_runner import run_jobs

BBC_CONFIGS=("bbc_core","bbc_valid","bbc_root","bbc_warm","bbc_alns","bbc_root_warm","bbc_root_alns","bbc_full_current")
def simple(method):
    c={"algorithm_family":method,"configuration_name":f"{method}_baseline","configuration_version":"1","status":"baseline"};c["configuration_hash"]=configuration_hash(c);return c
def main():
    p=argparse.ArgumentParser();p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot");p.add_argument("--output",default="experiments/pilot_calibration");p.add_argument("--small-budget",type=float,default=15);p.add_argument("--medium-budget",type=float,default=30);p.add_argument("--large-budget",type=float,default=45);p.add_argument("--threads",type=int,default=1);p.add_argument("--mip-gap",type=float,default=.03);p.add_argument("--resume",action="store_true");a=p.parse_args();root=Path(a.suite);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));selected={"small":"S01","medium":"M01","large":"L01"};budgets={"small":a.small_budget,"medium":a.medium_budget,"large":a.large_budget};jobs=[]
    for row in manifest["instances"]:
        if selected.get(row["size_class"])!=row["instance_id"]:continue
        path=root/row["relative_path"];digest=instance_digest(load_instance(path));base={"instance_id":row["instance_id"],"instance_path":path,"expected_digest":digest,"budget":budgets[row["size_class"]],"threads":a.threads,"mip_gap":a.mip_gap,"alloc_domain":"integer","handling_rate_scale":1.0,"outbound_policy":"proportional"}
        for method in ("direct","classical_benders","direct_alns"):
            seeds=(0,1,2) if method=="direct_alns" and row["size_class"]=="small" else (0,)
            for seed in seeds:jobs.append({**base,"method":method,"configuration":simple(method),"seed":seed})
        for name in BBC_CONFIGS:
            config=get_algorithm_configuration(name);stochastic=config["alns"] and row["size_class"]=="small";seeds=(0,1,2) if stochastic else (0,)
            for seed in seeds:jobs.append({**base,"method":"bbc_candidate","configuration":config,"seed":seed})
    rows=run_jobs(jobs,a.output,resume=a.resume,save_solutions=False,source_filename="raw_results.jsonl",command=" ".join(sys.argv));print(f"pilot calibration rows={len(rows)} requested={len(jobs)}");return 0
if __name__=="__main__":raise SystemExit(main())

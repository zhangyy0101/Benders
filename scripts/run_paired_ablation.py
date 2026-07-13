from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest,load_instance
from experiment_runner import run_jobs
CONFIGS=[f"C{i}_{n}" for i,n in enumerate(("bbc_core","core_analytic","core_aggregate","core_both_lb","both_lb_root","both_lb_warm","both_lb_warm_alns","both_lb_root_warm_alns","both_lb_root_warm_alns_valid"))]
def main():
 p=argparse.ArgumentParser();p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot2");p.add_argument("--output",default="experiments/paired_ablation");p.add_argument("--execute",action="store_true");p.add_argument("--seeds",nargs="+",type=int,default=[0,1,2]);p.add_argument("--threads",type=int,default=1);a=p.parse_args();root=Path(a.suite);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));budgets={"small":60,"medium":180,"large":600};jobs=[]
 for row in manifest["instances"]:
  path=root/row["relative_path"]
  for name in CONFIGS:
   for seed in a.seeds:jobs.append({"instance_id":row["instance_id"],"instance_path":path,"expected_digest":instance_digest(load_instance(path)),"method":"bbc_candidate","configuration":get_algorithm_configuration(name),"seed":seed,"budget":budgets[row["size_class"]],"threads":a.threads,"mip_gap":.03,"alloc_domain":"integer","handling_rate_scale":1.0,"outbound_policy":"proportional"})
 estimate={"runs":len(jobs),"serial_budget_seconds":sum(j["budget"] for j in jobs),"serial_budget_hours":sum(j["budget"] for j in jobs)/3600,"executed":a.execute};Path(a.output).mkdir(parents=True,exist_ok=True);(Path(a.output)/"budget_estimate.json").write_text(json.dumps(estimate,indent=2)+"\n",encoding="utf-8");print(json.dumps(estimate))
 if a.execute:run_jobs(jobs,a.output,resume=True,save_solutions=True,source_filename="raw_results.jsonl")
 return 0
if __name__=="__main__":raise SystemExit(main())

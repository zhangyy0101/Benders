from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest
from experiment_runner import run_jobs
from run_experiments import _simple_configuration
def main():
 p=argparse.ArgumentParser();p.add_argument("--suite",default="benchmarks/paper_exp_v1_pilot2");p.add_argument("--output",default="experiments/pilot2_smoke");p.add_argument("--budget",type=float,default=2.0);a=p.parse_args();root=Path(a.suite);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));selected={r["instance_id"]:r for r in manifest["instances"] if r["instance_id"] in {"S01","M01","L01"}};jobs=[]
 for iid,row in selected.items():
  base={"instance_id":iid,"instance_path":root/row["relative_path"],"expected_digest":row["digest"],"seed":0,"budget":a.budget,"threads":1,"mip_gap":.20,"alloc_domain":"integer","handling_rate_scale":1.0,"outbound_policy":"proportional"}
  for c in ("C0_bbc_core","C2_core_aggregate","C3_core_both_lb","C7_both_lb_root_warm_alns","C8_both_lb_root_warm_alns_valid"):jobs.append({**base,"method":"bbc_candidate","configuration":get_algorithm_configuration(c)})
  for method in ("direct","classical_benders","direct_alns"):jobs.append({**base,"method":method,"configuration":_simple_configuration(method)})
 rows=run_jobs(jobs,a.output,resume=True,rerun_failed=True,save_solutions=True,source_filename="raw_results.jsonl");ok=sum(r["status"]["ok"] for r in rows);print(f"pilot2 smoke: {ok}/{len(rows)} feasible runs");return 0 if all(r["status"]["status"]!="EXCEPTION" for r in rows) else 1
if __name__=="__main__":raise SystemExit(main())

from __future__ import annotations
import argparse,csv,json,random,statistics
from pathlib import Path
COMPARISONS=[("C1_core_analytic","C0_bbc_core","analytic_lb"),("C2_core_aggregate","C0_bbc_core","aggregate_lb"),("C3_core_both_lb","C2_core_aggregate","analytic_over_aggregate"),("C4_both_lb_root","C3_core_both_lb","root"),("C5_both_lb_warm","C3_core_both_lb","warm"),("C6_both_lb_warm_alns","C5_both_lb_warm","alns"),("C7_both_lb_root_warm_alns","C6_both_lb_warm_alns","root_interaction"),("C8_both_lb_root_warm_alns_valid","C7_both_lb_root_warm_alns","valid_inequalities")]
def key(r):
 i=r["identity"];return i["instance_id"],i["seed"],i["budget"],i["threads"],i["problem_protocol"]
def bootstrap(values,rng,n=2000):
 if not values:return (None,None)
 means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(n));return means[int(.025*n)],means[min(n-1,int(.975*n))]
def main():
 p=argparse.ArgumentParser();p.add_argument("--input",default="experiments/paired_ablation/raw_results.jsonl");p.add_argument("--output",default="experiments/paired_ablation");p.add_argument("--analysis-seed",type=int,default=20260713);a=p.parse_args();rows=[json.loads(x) for x in Path(a.input).read_text(encoding="utf-8").splitlines() if x.strip()];out=[];missing=[]
 for high,low,label in COMPARISONS:
  for size in ("small","medium","large","overall"):
   select=lambda r:size=="overall" or r["identity"]["instance_id"][0].lower()==size[0];hi={key(r):r for r in rows if select(r) and r["identity"]["configuration_name"]==high};lo={key(r):r for r in rows if select(r) and r["identity"]["configuration_name"]==low};common=sorted(set(hi)&set(lo));missing.extend({"comparison":label,"size":size,"key":repr(k)} for k in set(hi)^set(lo));record={"comparison":label,"candidate":high,"baseline":low,"size":size,"paired_run_count":len(common)}
   for metric,path in (("ub",("optimization","ub")),("lb",("optimization","lb")),("gap",("optimization","gap")),("runtime",("timing","wall_clock")),("primal_integral",("optimization","primal_integral")),("gap_integral",("optimization","gap_integral"))):
    vals=[]
    for k in common:
     x=hi[k].get(path[0],{}).get(path[1]);y=lo[k].get(path[0],{}).get(path[1])
     if x is not None and y is not None:vals.append(x-y)
    ci=bootstrap(vals,random.Random(a.analysis_seed));record.update({f"{metric}_difference_mean":statistics.mean(vals) if vals else None,f"{metric}_difference_median":statistics.median(vals) if vals else None,f"{metric}_bootstrap95_low":ci[0],f"{metric}_bootstrap95_high":ci[1]})
   gaps=[hi[k]["optimization"].get("gap")-lo[k]["optimization"].get("gap") for k in common if hi[k]["optimization"].get("gap") is not None and lo[k]["optimization"].get("gap") is not None];record.update(wins=sum(x< -1e-9 for x in gaps),ties=sum(abs(x)<=1e-9 for x in gaps),losses=sum(x>1e-9 for x in gaps),improvement_rate=sum(x< -1e-9 for x in gaps)/len(gaps) if gaps else None);out.append(record)
 root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
 for name,data in (("paired_summary.csv",out),("missing_pairs.csv",missing)):
  if data:
   with (root/name).open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 return 0
if __name__=="__main__":raise SystemExit(main())

from __future__ import annotations
import argparse,csv,json,statistics
from pathlib import Path
COMPONENTS=("open","concentration","distance","balance","conflict")
def main():
 p=argparse.ArgumentParser();p.add_argument("--input",default="experiments/pilot2_smoke/raw_results.jsonl");p.add_argument("--output",default="experiments/pilot2_smoke/component_share_analysis");a=p.parse_args();rows=[json.loads(x) for x in Path(a.input).read_text(encoding="utf-8").splitlines() if x.strip()];detail=[]
 for r in rows:
  e=r.get("evaluation") or {};parts=e.get("objective_components",e.get("components",{}));total=e.get("core_cost")
  if not r.get("status",{}).get("feasible_incumbent_found") or not total:continue
  item={"instance_id":r["identity"]["instance_id"],"size":r["identity"]["instance_id"][0],"configuration":r["identity"]["configuration_name"],"run_id":r["run_id"]};shares=[]
  for c in COMPONENTS:
   q=parts.get(c,{}) if isinstance(parts,dict) else {};weighted=q.get("weighted",0) if isinstance(q,dict) else 0;share=weighted/total;shares.append(share);item.update({f"{c}_raw":q.get("raw") if isinstance(q,dict) else None,f"{c}_normalized":q.get("normalized") if isinstance(q,dict) else None,f"{c}_weighted":weighted,f"{c}_share":share})
  item["dominant_component_over_70_percent"]=max(shares)>.70;item["extreme_component_over_85_percent"]=max(shares)>.85;detail.append(item)
 root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
 def summarize(field):
  result=[]
  for value in sorted({x[field] for x in detail}):
   subset=[x for x in detail if x[field]==value];row={field:value,"runs":len(subset)}
   for c in COMPONENTS:row[f"{c}_share_mean"]=statistics.mean(x[f"{c}_share"] for x in subset)
   row["dominant_rate"]=statistics.mean(x["dominant_component_over_70_percent"] for x in subset);row["extreme_rate"]=statistics.mean(x["extreme_component_over_85_percent"] for x in subset);result.append(row)
  return result
 outputs=(("summary_by_instance.csv",summarize("instance_id")),("summary_by_size.csv",summarize("size")),("summary_by_configuration.csv",summarize("configuration")))
 for name,data in outputs:
  if data:
   with (root/name).open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 (root/"objective_component_share_report.md").write_text(f"# Objective component shares\n\nFeasible runs analyzed: {len(detail)}. Flags report dominance only; weights were not changed.\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())

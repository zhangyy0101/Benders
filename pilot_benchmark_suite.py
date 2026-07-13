"""Pilot2 suite specifications, deterministic summaries, and independent audit."""
from __future__ import annotations
import csv,json,math,statistics
from pathlib import Path
from benchmark_io import instance_digest,load_instance
from benchmark_schema import PROBLEM_PROTOCOL,SCHEMA_VERSION
from data import simulate_old_inventory,validate_instance_units
from model_common import ship_groups
from model_concentration import has_joint_attribute_groups
from synthetic_instance_generator import GENERATOR_VERSION,SyntheticInstanceSpec

PILOT_VERSION="paper-exp-v1-pilot2.1"
SEEDS={**{f"S{i:02d}":1100+i for i in range(1,4)},**{f"M{i:02d}":2100+i for i in range(1,4)},**{f"L{i:02d}":3100+i for i in range(1,4)}}
RANGES={"small":{"groups":(8,14),"pods":(5,5),"overlap":(.25,.50),"pressure":(.25,.45)},"medium":{"groups":(14,24),"pods":(6,7),"overlap":(.50,.75),"pressure":(.45,.65)},"large":{"groups":(22,36),"pods":(8,8),"overlap":(.75,1),"pressure":(.60,.80)}}

def pilot_specs():
 result={};settings={
  "small":dict(num_blocks=3,bays_per_block=4,num_new_ships=2,num_old_ships=3,initial_utilization_range=(.20,.35),arrival_boxes_per_ship_range=(55,70),group_profile="pilot2_small",pod_count_range=(5,5),positive_group_count_range=(8,14),single_combination_pod_ratio_range=(.30,.50),arrival_overlap_ratio_range=(.25,.50),pressure_positive_ratio_range=(.25,.45)),
  "medium":dict(num_blocks=6,bays_per_block=6,num_new_ships=3,num_old_ships=4,initial_utilization_range=(.35,.50),arrival_boxes_per_ship_range=(110,145),group_profile="pilot2_medium",pod_count_range=(6,7),positive_group_count_range=(14,24),single_combination_pod_ratio_range=(.20,.40),arrival_overlap_ratio_range=(.50,.75),pressure_positive_ratio_range=(.45,.65)),
  "large":dict(num_blocks=10,bays_per_block=8,num_new_ships=5,num_old_ships=7,initial_utilization_range=(.45,.60),arrival_boxes_per_ship_range=(230,290),group_profile="pilot2_large",pod_count_range=(8,8),positive_group_count_range=(22,36),single_combination_pod_ratio_range=(.10,.30),arrival_overlap_ratio_range=(.75,1),pressure_positive_ratio_range=(.60,.80))}
 for size,v in settings.items():
  for number in range(1,4):
   iid=f"{size[0].upper()}{number:02d}";result[iid]=(size,SyntheticInstanceSpec(name=iid,num_periods=12,bay_capacity_boxes=50,num_berths=3,time_bucket_hours=6,alpha=1.1,handling_rate_boxes_per_hour=50,fixed_inbound_ratio_range=(.03,.09),outbound_pressure_ratio_range=(.08,.24),arrival_overlap_level=sum(v["arrival_overlap_ratio_range"])/2,peak_position_range=(.35,.65),mode_20ft_share=.5,**v))
 return result

def suite_metrics(d):
 active={j:[n for n in d["N"] if sum(d["Arrivals_interval"].get((j,s,n),0) for s in d["S"])>1e-9] for j in d["J_new"]};active_periods=[n for n in d["N"] if any(n in active[j] for j in d["J_new"])];overlap=sum(sum(n in active[j] for j in d["J_new"])>1 for n in active_periods)/max(1,len(active_periods))
 pair=[]
 for a,j in enumerate(d["J_new"]):
  for q in d["J_new"][a+1:]:pair.append(len(set(active[j])&set(active[q]))/max(1,len(set(active[j])|set(active[q]))))
 pressure=list(d["Block_Outbound_Vol"].values());positive=[v for v in pressure if v>1e-9];mean=sum(pressure)/len(pressure);sd=statistics.pstdev(pressure) if len(pressure)>1 else 0;ordered=sorted(pressure);p95=ordered[min(len(ordered)-1,math.ceil(.95*len(ordered))-1)]
 meta=d.get("ShipGroupGenerationMetadata",{});counts=[len(ship_groups(d,j)) for j in d["J_new"]];pods=[meta[j]["pod_count"] for j in d["J_new"]];single=sum(meta[j]["single_combination_pod_count"] for j in d["J_new"])/max(1,sum(pods));high=sum(v>=p95 and v>0 for v in pressure)/len(pressure)
 return {"num_global_groups":len(d["G"]),"positive_groups_mean_per_ship":sum(counts)/len(counts),"positive_groups_min_per_ship":min(counts),"positive_groups_max_per_ship":max(counts),"pod_count_mean_per_ship":sum(pods)/len(pods),"single_combination_pod_ratio":single,"height_coverage_rate":sum(len(meta[j]["height_coverage"])==2 for j in d["J_new"])/len(d["J_new"]),"weight_coverage_rate":sum(len(meta[j]["weight_coverage"])==2 for j in d["J_new"])/len(d["J_new"]),"size_coverage_rate":sum(len(meta[j]["size_coverage"])==2 for j in d["J_new"])/len(d["J_new"]),"arrival_overlap_ratio":overlap,"pairwise_window_overlap_mean":sum(pair)/len(pair) if pair else 0,"pairwise_window_overlap_max":max(pair,default=0),"peak_simultaneous_active_ships":max(sum(n in active[j] for j in d["J_new"]) for n in d["N"]),"active_period_count":len(active_periods),"zero_pressure_block_period_ratio":sum(v<=1e-9 for v in pressure)/len(pressure),"positive_pressure_block_period_ratio":len(positive)/len(pressure),"pressure_cv":sd/mean if mean else 0,"pressure_p95":p95,"high_pressure_block_period_ratio":high,"peak_pressure_period":max(d["Block_Outbound_Vol"],key=d["Block_Outbound_Vol"].get)[1]}

def instance_summary(d,instance_id,size_class,relative_path,seed):
 total=sum(d["Arrivals_interval"].values());capacity=sum(v["cap"] for v in d["I"].values());base={"protocol_version":PROBLEM_PROTOCOL,"schema_version":SCHEMA_VERSION,"generator_version":GENERATOR_VERSION,"pilot_version":PILOT_VERSION,"instance_id":instance_id,"relative_path":relative_path,"digest":instance_digest(d),"seed":seed,"size_class":size_class,"num_new_ships":len(d["J_new"]),"num_old_ships":len(d["J_old"]),"num_blocks":len(d["K"]),"num_bays":len(d["I_list"]),"num_periods":len(d["N"]),"num_groups":len(d["G"]),"total_arrivals":total,"initial_utilization":sum(d["initial_inventory_data"].values())/capacity,"concentration_available":has_joint_attribute_groups(d),"creation_status":"created","audit_status":"pending"};return {**base,**suite_metrics(d)}

def audit_instance(d,expected_digest=None,size_class=None):
 checks={};fail=[]
 def ck(name,ok,detail=None):
  checks[name]=bool(ok)
  if not ok:fail.append({"check":name,"detail":detail})
 validate_instance_units(d);sim=simulate_old_inventory(d);m=suite_metrics(d);r=RANGES.get(size_class or d["ScenarioName"][0].lower())
 ck("digest",expected_digest is None or instance_digest(d)==expected_digest);ck("12_periods",len(d["N"])==12);ck("old_outbound_feasible",sim["max_capacity_violation"]<=1e-6 and max(sim["unserved_outbound"].values(),default=0)<=1e-6)
 counts=[len(ship_groups(d,j)) for j in d["J_new"]];pods=[len(d["ActivePODsByShip"][j]) for j in d["J_new"]];ck("pod_counts",all(r["pods"][0]<=x<=r["pods"][1] for x in pods),pods);ck("positive_group_counts",all(r["groups"][0]<=x<=r["groups"][1] for x in counts),counts);single_range={"small":(.30,.50),"medium":(.20,.40),"large":(.10,.30)}[size_class];ck("single_combination_pod_ratio",single_range[0]<=m["single_combination_pod_ratio"]<=single_range[1],m["single_combination_pod_ratio"])
 ck("grouped_arrival_conservation",all(abs(sum(d["Arrivals_group_interval"].get((j,g,n),0) for g in ship_groups(d,j) if d["GroupSize"][g]==s)-d["Arrivals_interval"][j,s,n])<1e-7 for j in d["J_new"] for s in d["S"] for n in d["N"]));ck("minimum_active_group_volume",all(sum(d["Arrivals_group_interval"].get((j,g,n),0) for n in d["N"])>=2-1e-7 for j in d["J_new"] for g in ship_groups(d,j)))
 if d.get("GroupVolumeByShip"):
  ck("hierarchical_volume_conservation",all(sum(d["PODVolumeByShip"][j].values())==d["ships_config"][j]["total_boxes"] and sum(d["GroupVolumeByShip"][j].values())==d["ships_config"][j]["total_boxes"] and all(sum(d["PODSizeVolumeByShip"][j][p].values())==d["PODVolumeByShip"][j][p] for p in d["ActivePODsByShip"][j]) for j in d["J_new"]));ck("actual_size_share",all(abs(d["ActualSizeShareByShip"][j][str(s)]-sum(v for g,v in d["GroupVolumeByShip"][j].items() if d["GroupSize"][g]==s)/d["ships_config"][j]["total_boxes"])<1e-12 for j in d["J_new"] for s in d["S"]))
 ck("realized_overlap",r["overlap"][0]<=m["arrival_overlap_ratio"]<=r["overlap"][1],m["arrival_overlap_ratio"]);ck("pressure_sparsity",r["pressure"][0]<=m["positive_pressure_block_period_ratio"]<=r["pressure"][1],m["positive_pressure_block_period_ratio"]);ck("zero_and_high_pressure",m["zero_pressure_block_period_ratio"]>0 and m["high_pressure_block_period_ratio"]>0);ck("concentration_available",has_joint_attribute_groups(d));ck("attribute_coverage",m["height_coverage_rate"]>0 and m["weight_coverage_rate"]>0 and m["size_coverage_rate"]>0);ck("all_five_objective_signals",sum(d["Arrivals_interval"].values())>0 and len(set(d["Dist"].values()))>1 and max(d["Block_Outbound_Vol"].values())>0 and len(d["K"])>1 and has_joint_attribute_groups(d))
 return {"status":"PASS" if not fail else "FAIL","digest":instance_digest(d),"checks":checks,"failures":fail,"metrics":m}

def audit_suite(suite_dir):
 root=Path(suite_dir);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));reports=[]
 for row in manifest["instances"]:
  report=audit_instance(load_instance(root/row["relative_path"]),row["digest"],row["size_class"]);report.update(instance_id=row["instance_id"],relative_path=row["relative_path"]);reports.append(report)
 diversity={}
 for size in ("small","medium","large"):
  subset=[r for r in reports if r["instance_id"].lower().startswith(size[0])];diversity[size]={"overlap_varies":len({r["metrics"]["arrival_overlap_ratio"] for r in subset})>1,"pressure_varies":len({r["metrics"]["positive_pressure_block_period_ratio"] for r in subset})>1}
 diversity_ok=all(all(v.values()) for v in diversity.values());result={"pilot_version":manifest.get("pilot_version",PILOT_VERSION),"status":"PASS" if all(r["status"]=="PASS" for r in reports) and diversity_ok else "FAIL","instance_count":len(reports),"suite_diversity":diversity,"instances":reports};(root/"audit_report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(root/"audit_report.md").write_text("# Pilot2.1 benchmark audit\n\nOverall: **%s**\n\nSuite diversity: `%s`\n\n%s\n"%(result["status"],json.dumps(diversity,ensure_ascii=False),"\n".join(f"- {r['instance_id']}: {r['status']} ({', '.join(x['check'] for x in r['failures']) or 'all checks passed'})" for r in reports)),encoding="utf-8");status={r["instance_id"]:r["status"] for r in reports}
 for row in manifest["instances"]:row["audit_status"]=status[row["instance_id"]]
 write_manifests(root,manifest["instances"]);return result

def write_manifests(root,rows):
 fields=list(rows[0]);(root/"manifest.json").write_text(json.dumps({"pilot_version":PILOT_VERSION,"candidate_algorithm_frozen":False,"final_algorithm_frozen":False,"instances":rows},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
 with (root/"manifest.csv").open("w",newline="",encoding="utf-8") as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows({k:json.dumps(v,separators=(",",":")) if isinstance(v,(list,dict)) else v for k,v in row.items()} for row in rows)

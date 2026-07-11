"""Fixed pilot-suite specifications, summaries, and algorithm-independent audit."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from benchmark_io import compare_instances, instance_digest, load_instance
from benchmark_schema import PROBLEM_PROTOCOL, SCHEMA_VERSION
from data import simulate_old_inventory, validate_instance_units
from model_concentration import has_joint_attribute_groups
from synthetic_instance_generator import GENERATOR_VERSION, SyntheticInstanceSpec

PILOT_VERSION = "paper-exp-v1-pilot1"
SEEDS = {**{f"S{i:02d}": 1100 + i for i in range(1, 4)}, **{f"M{i:02d}": 2100 + i for i in range(1, 4)}, **{f"L{i:02d}": 3100 + i for i in range(1, 4)}}


def pilot_specs():
    result = {}
    settings = {
        "small": dict(num_blocks=3,bays_per_block=4,num_new_ships=2,num_old_ships=3,num_periods=4,initial_utilization_range=(.20,.35),arrival_boxes_per_ship_range=(45,65),arrival_overlap_level=.60,group_profile="standard"),
        "medium": dict(num_blocks=6,bays_per_block=6,num_new_ships=3,num_old_ships=4,num_periods=8,initial_utilization_range=(.35,.50),arrival_boxes_per_ship_range=(105,135),arrival_overlap_level=.78,group_profile="standard6"),
        "large": dict(num_blocks=10,bays_per_block=8,num_new_ships=5,num_old_ships=7,num_periods=12,initial_utilization_range=(.45,.60),arrival_boxes_per_ship_range=(220,270),arrival_overlap_level=.90,group_profile="standard6"),
    }
    prefixes = {"small":"S","medium":"M","large":"L"}
    for size_class, values in settings.items():
        for number in range(1,4):
            instance_id=f"{prefixes[size_class]}{number:02d}"
            result[instance_id]=(size_class,SyntheticInstanceSpec(
                name=instance_id,bay_capacity_boxes=50,num_berths=3,time_bucket_hours=6,
                alpha=1.1,handling_rate_boxes_per_hour=50,fixed_inbound_ratio_range=(.03,.09),
                outbound_pressure_ratio_range=(.08,.24),peak_position_range=(.35,.65),
                mode_20ft_share=.5,**values))
    return result


def instance_summary(instance, instance_id, size_class, relative_path, seed):
    simulation=simulate_old_inventory(instance);total=sum(instance["Arrivals_interval"].values());by_size={str(s):sum(v for (j,size,n),v in instance["Arrivals_interval"].items() if size==s) for s in instance["S"]};capacity=sum(v["cap"] for v in instance["I"].values());initial=sum(instance["initial_inventory_data"].values());pressure=list(instance["Block_Outbound_Vol"].values());active_overlap=0;active=0
    for n in instance["N"]:
        ships=sum(sum(instance["Arrivals_interval"][j,s,n] for s in instance["S"])>1e-9 for j in instance["J_new"])
        active+=ships>0;active_overlap+=ships>1
    tightness=[]
    final=max(instance["N"])
    for size in instance["S"]:
        bays=[i for i in instance["I_list"] if instance["Fixed_Bay_Mode"][i]==size];demand=instance["Alpha"]*sum(v for (j,s,n),v in instance["Arrivals_interval"].items() if s==size);available=sum(instance["I"][i]["cap"]-simulation["occupancy"][i,final] for i in bays);tightness.append(demand/available if available>0 else float("inf"))
    return {"protocol_version":PROBLEM_PROTOCOL,"schema_version":SCHEMA_VERSION,"generator_version":GENERATOR_VERSION,"pilot_version":PILOT_VERSION,"instance_id":instance_id,"relative_path":relative_path,"digest":instance_digest(instance),"seed":seed,"size_class":size_class,"num_new_ships":len(instance["J_new"]),"num_old_ships":len(instance["J_old"]),"num_blocks":len(instance["K"]),"num_bays":len(instance["I_list"]),"num_periods":len(instance["N"]),"num_groups":len(instance["G"]),"total_arrivals":total,"arrival_20ft":by_size.get("20",0),"arrival_40ft":by_size.get("40",0),"initial_utilization":initial/capacity if capacity else None,"arrival_overlap_ratio":active_overlap/active if active else 0,"pressure_min":min(pressure,default=0),"pressure_max":max(pressure,default=0),"pressure_mean":sum(pressure)/len(pressure) if pressure else 0,"capacity_tightness_max":max(tightness),"capacity_tightness_by_size":tightness,"concentration_available":has_joint_attribute_groups(instance),"creation_status":"created","audit_status":"pending"}


def audit_instance(instance, expected_digest=None):
    checks={};failures=[]
    def check(name, condition, detail=None):
        checks[name]=bool(condition)
        if not condition:failures.append({"check":name,"detail":detail})
    validate_instance_units(instance);simulation=simulate_old_inventory(instance);digest=instance_digest(instance)
    check("digest",expected_digest is None or digest==expected_digest,{"expected":expected_digest,"actual":digest});check("old_inventory",simulation["max_capacity_violation"]<=1e-6 and max(simulation["unserved_outbound"].values(),default=0)<=1e-6);check("positive_arrivals",sum(instance["Arrivals_interval"].values())>0);by_size={s:sum(v for (j,size,n),v in instance["Arrivals_interval"].items() if size==s) for s in instance["S"]};check("two_positive_sizes",all(by_size[s]>0 for s in instance["S"]),by_size);check("distinct_distances",len(set(instance["Dist"].values()))>1);pressure=list(instance["Block_Outbound_Vol"].values());check("nonuniform_positive_pressure",max(pressure,default=0)>0 and len(set(round(v,9) for v in pressure))>1);check("concentration_available",has_joint_attribute_groups(instance));check("multiple_compatible_bays",all(sum(instance["Fixed_Bay_Mode"][i]==instance["GroupSize"][g] for i in instance["I_list"])>1 for g in instance["G"]));overlap=any(sum(sum(instance["Arrivals_interval"][j,s,n] for s in instance["S"])>1e-9 for j in instance["J_new"])>1 for n in instance["N"]);check("arrival_overlap",overlap);capacity=sum(v["cap"] for v in instance["I"].values());util=sum(instance["initial_inventory_data"].values())/capacity;check("nonzero_safe_utilization",0<util<.85,util)
    final=max(instance["N"]);tight=[];handling_ok=True
    for size in instance["S"]:
        bays=[i for i in instance["I_list"] if instance["Fixed_Bay_Mode"][i]==size];demand=instance["Alpha"]*sum(v for (j,s,n),v in instance["Arrivals_interval"].items() if s==size);available=sum(instance["I"][i]["cap"]-simulation["occupancy"][i,final] for i in bays);tight.append(demand/available if available>0 else float("inf"))
        for j in instance["J_new"]:
            for n in instance["N"]:handling_ok &= instance["Alpha"]*instance["Arrivals_interval"][j,size,n] <= sum(instance["Bay_Handling_Rate"][i,n]*instance["Intervals"][n]["dur"] for i in bays)+1e-6
    check("capacity_feasible_not_trivially_loose",max(tight)<1 and max(tight)>.15,tight);check("handling_necessary_condition",handling_ok);check("grouped_arrivals",all(abs(sum(instance["Arrivals_group_interval"][j,g,n] for g in instance["G"] if instance["GroupSize"][g]==s)-instance["Arrivals_interval"][j,s,n])<=1e-6 for j in instance["J_new"] for s in instance["S"] for n in instance["N"]));signals={"open":sum(instance["Arrivals_interval"].values())>0 and instance["handling_rate_boxes_per_hour"]>0 if "handling_rate_boxes_per_hour" in instance else True,"concentration":has_joint_attribute_groups(instance),"distance":len(set(instance["Dist"].values()))>1,"balance":len(instance["K"])>1,"conflict":max(pressure)>0 and len(set(round(v,9) for v in pressure))>1};check("all_objective_signals",all(signals.values()),signals)
    return {"status":"PASS" if not failures else "FAIL","digest":digest,"checks":checks,"failures":failures,"metrics":{"initial_utilization":util,"capacity_tightness_by_size":tight,"objective_signals":signals}}


def audit_suite(suite_dir):
    root=Path(suite_dir);manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"));reports=[]
    for row in manifest["instances"]:
        path=root/row["relative_path"];instance=load_instance(path);report=audit_instance(instance,row["digest"]);report.update({"instance_id":row["instance_id"],"relative_path":row["relative_path"]});reports.append(report)
    result={"pilot_version":PILOT_VERSION,"status":"PASS" if all(r["status"]=="PASS" for r in reports) else "FAIL","instance_count":len(reports),"instances":reports};(root/"audit_report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");lines=["# Pilot benchmark audit", "",f"Overall: **{result['status']}**", "", "| Instance | Status | Failed checks |", "|---|---|---|"]+[f"| {r['instance_id']} | {r['status']} | {', '.join(x['check'] for x in r['failures']) or '—'} |" for r in reports];(root/"audit_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8");status_by_id={r["instance_id"]:r["status"] for r in reports}
    for row in manifest["instances"]:row["audit_status"]=status_by_id[row["instance_id"]]
    write_manifests(root,manifest["instances"]);return result


def write_manifests(root, rows):
    fields=list(rows[0]);(root/"manifest.json").write_text(json.dumps({"pilot_version":PILOT_VERSION,"instances":rows},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with (root/"manifest.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows({k:json.dumps(v,separators=(",",":")) if isinstance(v,list) else v for k,v in row.items()} for row in rows)

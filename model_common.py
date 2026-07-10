"""Shared deterministic data, occupancy and objective helpers for Route A."""
from __future__ import annotations
import math
from data import simulate_old_inventory

def new_groups(data): return list(data.get("G") or data["S"])
def group_size(data,g): return int(data.get("GroupSize",{}).get(g, data.get("GroupAttrs",{}).get(g,{}).get("size",g)))
def group_attr(data,g,attr,default="ALL"):
    maps={"pod":"GroupPOD","height":"GroupHeight","weight_class":"GroupWeightClass"}
    return str(data.get(maps[attr],{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get(attr,default)))
def arrival(data,j,g,n):
    grouped=data.get("Arrivals_group_interval",{})
    return float(grouped[(j,g,n)] if (j,g,n) in grouped else data["Arrivals_interval"].get((j,group_size(data,g),n),0.0))
def attribute_values(data,attr): return sorted({group_attr(data,g,attr) for g in new_groups(data) if group_attr(data,g,attr)!="ALL"})
def has_attribute_data(data):
    groups=list(data.get("G") or []);sizes=data.get("GroupSize",{});grouped=data.get("Arrivals_group_interval",{})
    if not groups or any(g not in sizes for g in groups): return False
    if any((j,g,n) not in grouped for j in data["J_new"] for g in groups for n in data["N"]):return False
    return any(len(attribute_values(data,a))>=2 for a in ("pod","weight_class","height"))
def ordered_periods(data): return sorted(data["N"])
def predecessor_map(data):
    periods=ordered_periods(data); return {n:(periods[pos-1] if pos else None) for pos,n in enumerate(periods)}
def required_reserve(data,j,g,n,alloc_domain):
    need=float(data["Alpha"])*sum(arrival(data,j,g,nn) for nn in ordered_periods(data) if nn<=n)
    return float(math.ceil(need-1e-9)) if alloc_domain=="integer" else need

def compute_old_occupancy(data): return simulate_old_inventory(data)["occupancy"]

def fixed_in_block(data):
    return {(k,n):sum(float(data.get("Fixed_In_Flow",{}).get((j,s,i,n),0)) for i in bays for j in data.get("J_old",[]) for s in data["S"]) for k,bays in data["Bays_in_Block"].items() for n in data["N"]}
def outbound_pressure(data):
    raw=data.get("Block_Outbound_Vol",{}); N=sorted(data["N"]); result={}
    for k in data["K"]:
        for pos,n in enumerate(N): result[k,n]=float(raw.get((k,n),0))+.5*(float(raw.get((k,N[pos-1]),0)) if pos else 0)+.5*(float(raw.get((k,N[pos+1]),0)) if pos+1<len(N) else 0)
    return result
def objective_scale_factor(weights): return max(float(getattr(weights,"objective_scale",1)),1e-9)
def objective_scales(data):
    total=sum(arrival(data,j,g,n) for j in data["J_new"] for g in new_groups(data) for n in data["N"]); durations=sum(float(data["Intervals"][n]["dur"]) for n in data["N"]); pressure=outbound_pressure(data)
    max_in=max([sum(arrival(data,j,g,n) for j in data["J_new"] for g in new_groups(data)) for n in data["N"]]+[1]); max_dist=max([float(v) for v in data["Dist"].values()]+[1]); max_pressure=max(list(pressure.values())+[1])
    return {"open":max(1,len(data["I_list"])*len(data["J_new"])*durations),"distance":max(1,max_dist*total),"conflict":max(1,max_pressure*total),"balance":max(1,len(data["N"])*len(data["K"])*max_in)}
def attribute_scales(data,attribute_scope):
    if attribute_scope not in {"final","horizon"}: raise ValueError("invalid attribute scope")
    periods=1 if attribute_scope=="final" else len(data["N"])
    return {"pod_spread":max(1,len(data["J_new"])*len(data["K"])*max(1,len(attribute_values(data,"pod")))*periods),"weight_spread":max(1,len(data["J_new"])*len(data["K"])*max(1,len(attribute_values(data,"weight_class")))*periods),"height_mix":max(1,len(data["I_list"])*max(1,len(attribute_values(data,"height"))-1)*periods)}

def raw_components(data,solution,attribute_scope="final",attribute_basis="inventory"):
    G,N=new_groups(data),data["N"]; periods=[max(N)] if attribute_scope=="final" and N else N; fixed=fixed_in_block(data); pressure=outbound_pressure(data)
    open_raw=sum(solution.get("x",{}).get((i,j,n),0)*float(data["Intervals"][n]["dur"]) for i in data["I_list"] for j in data["J_new"] for n in N)
    totals={(k,n):fixed[k,n]+sum(solution.get("in_share",{}).get((j,k,g,n),0) for j in data["J_new"] for g in G) for k in data["K"] for n in N}
    balance=sum(abs(totals[k,n]-sum(totals[kk,n] for kk in data["K"])/len(data["K"])) for k in data["K"] for n in N)
    conflict=sum(pressure[k,n]*sum(solution.get("in_share",{}).get((j,k,g,n),0) for j in data["J_new"] for g in G) for k in data["K"] for n in N)
    basis="inv" if attribute_basis=="inventory" else "alloc_boxes"
    def spread(attr): return sum(any(solution.get(basis,{}).get((j,g,i,n),0)>1e-6 if basis=="inv" else solution.get(basis,{}).get((i,j,g,n),0)>1e-6 for i in data["Bays_in_Block"][k] for g in G if group_attr(data,g,attr)==value) for j in data["J_new"] for value in attribute_values(data,attr) for k in data["K"] for n in periods)
    height=sum(max(0,len({group_attr(data,g,"height") for j in data["J_new"] for g in G if (solution.get("inv",{}).get((j,g,i,n),0) if basis=="inv" else solution.get("alloc_boxes",{}).get((i,j,g,n),0))>1e-6})-1) for i in data["I_list"] for n in periods)
    return {"obj_x":open_raw,"real_l1":balance,"obj_conflict":conflict,"pod_spread":spread("pod"),"weight_spread":spread("weight_class"),"height_mix":height,"in_total":totals}
def attribute_score(data,weights,raw,attribute_scope="final"):
    s=attribute_scales(data,attribute_scope); w=weights.attribute
    return objective_scale_factor(weights)*(w.pod_spread*raw["pod_spread"]/s["pod_spread"]+w.weight_spread*raw["weight_spread"]/s["weight_spread"]+w.height_mix*raw["height_mix"]/s["height_mix"])
def handling_diagnostics(data,solution,tolerance=1e-6):
    values=[]; active=0; binding=0
    for i in data["I_list"]:
        for j in data["J_new"]:
            for n in data["N"]:
                denom=float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"]); used=float(data["Alpha"])*sum(solution.get("din",{}).get((j,g,i,n),0) for g in new_groups(data)); util=used/denom if denom>0 else (math.inf if used>tolerance else 0); is_active=solution.get("x",{}).get((i,j,n),0)>.5
                if is_active: values.append(util); active+=1
                if is_active and abs(denom-used)<=tolerance*max(1,denom): binding+=1
    return {"max_handling_utilization":max(values,default=0.0),"average_active_handling_utilization":sum(values)/len(values) if values else 0.0,"number_of_binding_handling_constraints":binding,"number_of_active_bays":active}

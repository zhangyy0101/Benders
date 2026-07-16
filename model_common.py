"""Shared constants, groups, occupancy and objective scales for Route B."""
from __future__ import annotations
import math
from data import simulate_old_inventory
def groups(data):return list(data.get("G") or data["S"])
def ship_groups(data,ship):
    """Active groups for one ship; legacy instances remain dense."""
    active=data.get("ActiveGroupsByShip")
    return groups(data) if active is None else list(active.get(ship,()))
def ship_group_pairs(data):return [(j,g) for j in data["J_new"] for g in ship_groups(data,j)]
def demand_types(data):
    """Sparse positive demand types as (ship, POD, size, height)."""
    return sorted({(j,group_attr(data,g,"pod"),group_size(data,g),group_attr(data,g,"height")) for j,g in ship_group_pairs(data) if sum(arrival(data,j,g,n) for n in data["N"])>1e-9})
def groups_of_type(data,j,p,s,h):return [g for jj,g in ship_group_pairs(data) if jj==j and group_attr(data,g,"pod")==p and group_size(data,g)==int(s) and group_attr(data,g,"height")==h]
def type_arrival(data,j,p,s,h,n):return sum(arrival(data,j,g,n) for g in groups_of_type(data,j,p,s,h))
def type_reserve(data,j,p,s,h,n,alloc_domain):
    value=sum(type_arrival(data,j,p,s,h,t) for t in data["N"] if t<=n);return float(math.ceil(value-1e-9)) if alloc_domain=="integer" else float(value)
def group_size(data,g):return int(data.get("GroupSize",{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get("size",g)))
def group_attr(data,g,name,default="ALL"):
    maps={"pod":"GroupPOD","height":"GroupHeight","weight_class":"GroupWeightClass"};return str(data.get(maps[name],{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get(name,default)))
def arrival(data,j,g,n):
    g=data.get("LegacyGroupMap",{}).get(g,g)
    grouped=data.get("Arrivals_group_interval",{})
    if data.get("ActiveGroupsByShip") is not None and g not in data["ActiveGroupsByShip"].get(j,()):return 0.0
    return float(grouped[j,g,n] if (j,g,n) in grouped else data["Arrivals_interval"].get((j,group_size(data,g),n),0))
def old_occupancy(data):return simulate_old_inventory(data)["occupancy"]
def remaining_capacity(data):
    old=old_occupancy(data);return {(i,n):float(data["I"][i]["cap"])-old.get((i,n),0) for i in data["I_list"] for n in data["N"]}
def fixed_in_block(data):return {(k,n):sum(float(data["Fixed_In_Flow"].get((j,s,i,n),0)) for i in bays for j in data["J_old"] for s in data["S"]) for k,bays in data["Bays_in_Block"].items() for n in data["N"]}
def outbound_pressure(data):
    raw=data["Block_Outbound_Vol"];N=data["N"];result={}
    for k in data["K"]:
     for pos,n in enumerate(N):result[k,n]=float(raw.get((k,n),0))+.5*(float(raw.get((k,N[pos-1]),0)) if pos else 0)+.5*(float(raw.get((k,N[pos+1]),0)) if pos+1<len(N) else 0)
    return result
def objective_scales(data):
    pairs=ship_group_pairs(data);total=sum(arrival(data,j,g,n) for j,g in pairs for n in data["N"]);duration=sum(float(data["Intervals"][n]["dur"]) for n in data["N"]);maxin=max([sum(arrival(data,j,g,n) for j,g in pairs) for n in data["N"]]+[1]);pressure=outbound_pressure(data)
    return {"open":max(1,len(data["I_list"])*len(data["J_new"])*duration),"distance":max(1,max([float(v) for v in data["Dist"].values()]+[1])*total),"balance":max(1,len(data["K"])*len(data["N"])*maxin),"conflict":max(1,max(list(pressure.values())+[1])*total)}
def scale_factor(weights):return max(float(weights.objective_scale),1e-9)
def derive_activation(data,alloc,tolerance=1e-6):
    """Compatibility/KPI view: a ship uses a bay-period iff it has reserved boxes there."""
    return {(i,j,n):float(any(float(alloc.get((i,j,g,n),0))>tolerance for g in ship_groups(data,j))) for i in data["I_list"] for j in data["J_new"] for n in data["N"]}
def reconstruct_inventory(data,din):
    """Inventory is a derived cumulative flow, not an optimization variable."""
    return {(j,g,i,n):float(data["initial_inventory_data"].get((i,j,g),0))+sum(float(din.get((j,g,i,t),0)) for t in data["N"] if t<=n) for j,g in ship_group_pairs(data) for i in data["I_list"] for n in data["N"]}
def first_stage_cost(data,weights,alloc,*,alloc_domain="integer",concentration_enabled=True):
    from model_concentration import evaluate_joint_group_concentration
    concentration=evaluate_joint_group_concentration(data,{"alloc_boxes":alloc},alloc_domain=alloc_domain,enabled=concentration_enabled);cc=0.0 if not concentration["enabled"] else scale_factor(weights)*weights.master.concentration*concentration["normalized"]
    return {"open_cost":0.0,"concentration_cost":cc,"total":cc,"concentration":concentration}
def required_reserve(data,j,g,n,alloc_domain):
    value=sum(arrival(data,j,g,t) for t in data["N"] if t<=n);return float(math.ceil(value-1e-9)) if alloc_domain=="integer" else float(value)

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
def group_size(data,g):return int(data.get("GroupSize",{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get("size",g)))
def group_attr(data,g,name,default="ALL"):
    maps={"pod":"GroupPOD","height":"GroupHeight","weight_class":"GroupWeightClass"};return str(data.get(maps[name],{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get(name,default)))
def arrival(data,j,g,n):
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
def open_cost(data,weights,x):
    raw=sum(float(x.get((i,j,n),0))*float(data["Intervals"][n]["dur"]) for i in data["I_list"] for j in data["J_new"] for n in data["N"]);return scale_factor(weights)*weights.master.x*raw/objective_scales(data)["open"]
def first_stage_cost(data,weights,x,alloc,*,alloc_domain="integer",concentration_enabled=True):
    from model_concentration import evaluate_joint_group_concentration
    concentration=evaluate_joint_group_concentration(data,{"alloc_boxes":alloc},alloc_domain=alloc_domain,enabled=concentration_enabled);cc=0.0 if not concentration["enabled"] else scale_factor(weights)*weights.master.concentration*concentration["normalized"]
    oc=open_cost(data,weights,x);return {"open_cost":oc,"concentration_cost":cc,"total":oc+cc,"concentration":concentration}
def required_reserve(data,j,g,n,alloc_domain):
    value=float(data["Alpha"])*sum(arrival(data,j,g,t) for t in data["N"] if t<=n);return float(math.ceil(value-1e-9)) if alloc_domain=="integer" else value
def add_common_master_valid_inequalities(model,data,variables,*,enabled=True):
    if not enabled:return []
    x,alloc=variables["x"],variables["alloc_boxes"];I,J,N=data["I_list"],data["J_new"],data["N"];modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};alpha=float(data["Alpha"]);added=[]
    for j in J:
      for size in data["S"]:
       bays=[i for i in I if modes[i]==int(size)];sg=[g for g in ship_groups(data,j) if group_size(data,g)==int(size)]
       for n in N:
        need=sum(arrival(data,j,g,n) for g in sg);caps=[float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"]) for i in bays];maxcap=max(caps,default=0)
        if need>1e-9:added.append(model.addConstr(sum(caps[p]*x[i,j,n] for p,i in enumerate(bays))>=alpha*need,name=f"common_handling_{j}_{size}_{n}"))
        if need>1e-9 and maxcap>0:added.append(model.addConstr(sum(x[i,j,n] for i in bays)>=math.ceil(alpha*need/maxcap-1e-9),name=f"common_min_bays_{j}_{size}_{n}"))
    if not any(float(v)>1e-9 for v in data.get("New_Outbound_Req",{}).values()):
      for n in N[1:]:
       for j in J:
        for i in I:added.append(model.addConstr(x[i,j,n]>=x[i,j,n-1],name=f"common_x_mono_{i}_{j}_{n}"))
    return added

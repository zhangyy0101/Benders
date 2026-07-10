"""Shared constants, groups, occupancy and objective scales for Route B."""
from __future__ import annotations
def groups(data):return list(data.get("G") or data["S"])
def group_size(data,g):return int(data.get("GroupSize",{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get("size",g)))
def group_attr(data,g,name,default="ALL"):
    maps={"pod":"GroupPOD","height":"GroupHeight","weight_class":"GroupWeightClass"};return str(data.get(maps[name],{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get(name,default)))
def arrival(data,j,g,n):
    grouped=data.get("Arrivals_group_interval",{});return float(grouped[j,g,n] if (j,g,n) in grouped else data["Arrivals_interval"].get((j,group_size(data,g),n),0))
def old_occupancy(data):
    I,J,S,N=data["I_list"],data["J_old"],data["S"],data["N"];inv={(i,j,s):float(data["initial_inventory_data"].get((i,j,s),0)) for i in I for j in J for s in S};out={}
    for n in N:
      for i in I:
       for j in J:
        for s in S:inv[i,j,s]+=float(data["Fixed_In_Flow"].get((j,s,i,n),0))
      for k,bays in data["Bays_in_Block"].items():
       for j in J:
        left=float(data["Block_Outbound_Req"].get((k,j,n),0))
        for i in sorted(bays):
         for s in S:
          take=min(left,inv[i,j,s]);inv[i,j,s]-=take;left-=take
      for i in I:out[i,n]=sum(inv[i,j,s] for j in J for s in S)
    return out
def remaining_capacity(data):
    old=old_occupancy(data);return {(i,n):max(0,float(data["I"][i]["cap"])-old.get((i,n),0)) for i in data["I_list"] for n in data["N"]}
def fixed_in_block(data):return {(k,n):sum(float(data["Fixed_In_Flow"].get((j,s,i,n),0)) for i in bays for j in data["J_old"] for s in data["S"]) for k,bays in data["Bays_in_Block"].items() for n in data["N"]}
def outbound_pressure(data):
    raw=data["Block_Outbound_Vol"];N=data["N"];result={}
    for k in data["K"]:
     for pos,n in enumerate(N):result[k,n]=float(raw.get((k,n),0))+.5*(float(raw.get((k,N[pos-1]),0)) if pos else 0)+.5*(float(raw.get((k,N[pos+1]),0)) if pos+1<len(N) else 0)
    return result
def objective_scales(data):
    total=sum(arrival(data,j,g,n) for j in data["J_new"] for g in groups(data) for n in data["N"]);duration=sum(float(data["Intervals"][n]["dur"]) for n in data["N"]);maxin=max([sum(arrival(data,j,g,n) for j in data["J_new"] for g in groups(data)) for n in data["N"]]+[1]);pressure=outbound_pressure(data)
    return {"open":max(1,len(data["I_list"])*len(data["J_new"])*duration),"distance":max(1,max([float(v) for v in data["Dist"].values()]+[1])*total),"balance":max(1,len(data["K"])*len(data["N"])*maxin),"conflict":max(1,max(list(pressure.values())+[1])*total)}
def scale_factor(weights):return max(float(weights.objective_scale),1e-9)
def open_cost(data,weights,x):
    raw=sum(float(x.get((i,j,n),0))*float(data["Intervals"][n]["dur"]) for i in data["I_list"] for j in data["J_new"] for n in data["N"]);return scale_factor(weights)*weights.master.x*raw/objective_scales(data)["open"]

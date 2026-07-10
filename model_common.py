"""Shared deterministic data, occupancy and objective helpers for Route A."""
from __future__ import annotations
import math

def new_groups(data): return list(data.get("G") or data["S"])
def group_size(data,g): return int(data.get("GroupSize",{}).get(g, data.get("GroupAttrs",{}).get(g,{}).get("size",g)))
def group_attr(data,g,attr,default="ALL"):
    maps={"pod":"GroupPOD","height":"GroupHeight","weight_class":"GroupWeightClass"}
    return str(data.get(maps[attr],{}).get(g,data.get("GroupAttrs",{}).get(g,{}).get(attr,default)))
def arrival(data,j,g,n):
    grouped=data.get("Arrivals_group_interval",{})
    return float(grouped[(j,g,n)] if (j,g,n) in grouped else data["Arrivals_interval"].get((j,group_size(data,g),n),0.0))
def attribute_values(data,attr): return sorted({group_attr(data,g,attr) for g in new_groups(data) if group_attr(data,g,attr)!="ALL"})

def compute_old_occupancy(data):
    I,J,S,N=data["I_list"],data.get("J_old",[]),data["S"],data["N"]
    inv={(i,j,s):float(data.get("initial_inventory_data",{}).get((i,j,s),0)) for i in I for j in J for s in S}; result={}
    for n in sorted(N):
        for i in I:
            for j in J:
                for s in S: inv[i,j,s]+=float(data.get("Fixed_In_Flow",{}).get((j,s,i,n),0))
        for k,bays in data["Bays_in_Block"].items():
            for j in J:
                left=float(data.get("Block_Outbound_Req",{}).get((k,j,n),0))
                for i in sorted(bays):
                    for s in S:
                        take=min(left,inv[i,j,s]); inv[i,j,s]-=take; left-=take
        for i in I: result[i,n]=sum(inv[i,j,s] for j in J for s in S)
    return result

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
    return {"open":max(1,len(data["I_list"])*len(data["J_new"])*durations),"distance":max(1,max_dist*total),"conflict":max(1,max_pressure*total),"balance":max(1,len(data["N"])*len(data["K"])*max_in),"pod_spread":max(1,len(data["J_new"])*len(data["K"])*max(1,len(attribute_values(data,"pod")))),"weight_spread":max(1,len(data["J_new"])*len(data["K"])*max(1,len(attribute_values(data,"weight_class")))),"height_mix":max(1,len(data["I_list"])*len(data["N"])*max(1,len(attribute_values(data,"height"))-1))}

def raw_components(data,solution,attribute_scope="final"):
    G,N=new_groups(data),data["N"]; periods=[max(N)] if attribute_scope=="final" and N else N; fixed=fixed_in_block(data); pressure=outbound_pressure(data)
    open_raw=sum(solution.get("x",{}).get((i,j,n),0)*float(data["Intervals"][n]["dur"]) for i in data["I_list"] for j in data["J_new"] for n in N)
    totals={(k,n):fixed[k,n]+sum(solution.get("in_share",{}).get((j,k,g,n),0) for j in data["J_new"] for g in G) for k in data["K"] for n in N}
    balance=sum(abs(totals[k,n]-sum(totals[kk,n] for kk in data["K"])/len(data["K"])) for k in data["K"] for n in N)
    conflict=sum(pressure[k,n]*sum(solution.get("in_share",{}).get((j,k,g,n),0) for j in data["J_new"] for g in G) for k in data["K"] for n in N)
    def spread(attr): return sum(any(solution.get("alloc_boxes",{}).get((i,j,g,n),0)>1e-6 for i in data["Bays_in_Block"][k] for g in G if group_attr(data,g,attr)==value) for j in data["J_new"] for value in attribute_values(data,attr) for k in data["K"] for n in periods)
    height=sum(max(0,len({group_attr(data,g,"height") for j in data["J_new"] for g in G if solution.get("alloc_boxes",{}).get((i,j,g,n),0)>1e-6})-1) for i in data["I_list"] for n in periods)
    return {"obj_x":open_raw,"real_l1":balance,"obj_conflict":conflict,"pod_spread":spread("pod"),"weight_spread":spread("weight_class"),"height_mix":height,"in_total":totals}
def attribute_score(data,weights,raw):
    s=objective_scales(data); w=weights.attribute
    return objective_scale_factor(weights)*(w.pod_spread*raw["pod_spread"]/s["pod_spread"]+w.weight_spread*raw["weight_spread"]/s["weight_spread"]+w.height_mix*raw["height_mix"]/s["height_mix"])

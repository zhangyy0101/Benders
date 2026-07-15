"""Bay concentration by ship and discharge POD."""
from __future__ import annotations
from model_common import group_attr,group_size,remaining_capacity,required_reserve,ship_group_pairs,ship_groups

TOL=1e-9
def has_joint_attribute_groups(data):
    return bool(data.get("G") and all("pod" in data.get("GroupAttrs",{}).get(g,{}) and "height" in data.get("GroupAttrs",{}).get(g,{}) for g in data["G"]) and all((j,g,n) in data.get("Arrivals_group_interval",{}) for j,g in ship_group_pairs(data) for n in data["N"]))

def concentration_metadata(data,alloc_domain="integer"):
    available=has_joint_attribute_groups(data);final=max(data["N"]);rem=remaining_capacity(data);positive=[];M={};feasible={};groups_by={}
    if available:
      for j in data["J_new"]:
        pods=sorted({group_attr(data,g,"pod") for g in ship_groups(data,j)})
        for pod in pods:
          gs=[g for g in ship_groups(data,j) if group_attr(data,g,"pod")==pod];required=sum(required_reserve(data,j,g,final,alloc_domain) for g in gs)
          if required<=TOL:continue
          positive.append((j,pod));groups_by[j,pod]=gs;feasible[j,pod]=[]
          for i in data["I_list"]:
            compatible=[g for g in gs if group_size(data,g)==int(data["Fixed_Bay_Mode"][i])]
            value=max(0,min(sum(required_reserve(data,j,g,final,alloc_domain) for g in compatible),rem[i,final]));M[j,pod,i]=value
            if value>TOL:feasible[j,pod].append(i)
    return {"available":available,"final_period":final,"positive_ship_pods":positive,"positive_ship_groups":positive,"groups_by_ship_pod":groups_by,"big_m":M,"feasible_bays":feasible,"scale":max(1,len(positive))}

def build_joint_group_concentration(model,data,alloc_vars,*,alloc_domain="integer",enabled=True,x_vars=None,relax=False):
    import gurobipy as gp
    from gurobipy import GRB
    relax=relax or model.ModelName.endswith("_lp");meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);use={}
    if active:
      indices=[(j,pod,i) for j,pod in meta["positive_ship_pods"] for i in meta["feasible_bays"][j,pod]];use=model.addVars(indices,lb=0,ub=1,vtype=GRB.CONTINUOUS if relax else GRB.BINARY,name="ship_pod_bay_use");final=meta["final_period"]
      for j,pod,i in indices:
        quantity=gp.quicksum(alloc_vars[i,j,g,final] for g in meta["groups_by_ship_pod"][j,pod] if (i,j,g,final) in alloc_vars);model.addConstr(quantity<=meta["big_m"][j,pod,i]*use[j,pod,i],name=f"pod_concentration_link_{i}_{j}_{pod}")
        if alloc_domain=="integer":model.addConstr(quantity>=use[j,pod,i],name=f"pod_concentration_support_{i}_{j}_{pod}")
      for var in use.values():var.BranchPriority=25
    raw=gp.quicksum(use.values()) if active else 0.0
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","use_vars":use,"raw_used_bays":raw,"normalized_expression":raw/meta["scale"] if active else 0.0}

def evaluate_joint_group_concentration(data,solution,*,alloc_domain="integer",enabled=True,tolerance=1e-6):
    meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);used={};total=0;alloc=solution.get("alloc_boxes",{})
    if active:
      final=meta["final_period"]
      for j,pod in meta["positive_ship_pods"]:
        used[j,pod]=[i for i in meta["feasible_bays"][j,pod] if sum(float(alloc.get((i,j,g,final),0)) for g in meta["groups_by_ship_pod"][j,pod])>tolerance];total+=len(used[j,pod])
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","used_bays":used,"used_bays_total":total if active else None,"raw_used_bays":total if active else None,"normalized":None if not active else total/meta["scale"]}

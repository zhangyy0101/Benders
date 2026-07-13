"""Canonical bay-level joint ship-group concentration formulation."""
from __future__ import annotations
from model_common import group_size,remaining_capacity,required_reserve,ship_group_pairs

TOL=1e-9
def has_joint_attribute_groups(data):
    G=list(data.get("G") or []);attrs=data.get("GroupAttrs",{});arr=data.get("Arrivals_group_interval",{})
    if not G or any(g not in attrs or g not in data.get("GroupSize",{}) for g in G):return False
    if any(any(str(attrs[g].get(a,"ALL")).upper() in {"","ALL","NONE"} for a in ("pod","height","weight_class")) for g in G):return False
    return all((j,g,n) in arr for j,g in ship_group_pairs(data) for n in data["N"])

def concentration_metadata(data,alloc_domain="integer"):
    available=has_joint_attribute_groups(data);final=max(data["N"]);rem=remaining_capacity(data);positive=[];M={};feasible={}
    if available:
      for j,g in ship_group_pairs(data):
        required=required_reserve(data,j,g,final,alloc_domain)
        if required<=TOL:continue
        positive.append((j,g));feasible[j,g]=[]
        for i in data["I_list"]:
         if int(data["Fixed_Bay_Mode"][i])==group_size(data,g):
          value=max(0,min(required,rem[i,final]));M[j,g,i]=value
          if value>TOL:feasible[j,g].append(i)
    scale=max(1,sum(len(feasible[p]) for p in positive))
    return {"available":available,"final_period":final,"positive_ship_groups":positive,"big_m":M,"feasible_bays":feasible,"scale":scale}

def build_joint_group_concentration(model,data,alloc_vars,*,alloc_domain="integer",enabled=True,x_vars=None,relax=False):
    import gurobipy as gp
    from gurobipy import GRB

    relax=relax or model.ModelName.endswith("_lp");meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);use={}
    if active:
      indices=[(j,g,i) for j,g in meta["positive_ship_groups"] for i in meta["feasible_bays"][j,g]];use=model.addVars(indices,lb=0,ub=1,vtype=GRB.CONTINUOUS if relax else GRB.BINARY,name="joint_group_bay_use");final=meta["final_period"]
      for j,g,i in indices:
       alloc=alloc_vars[i,j,g,final];model.addConstr(alloc<=meta["big_m"][j,g,i]*use[j,g,i],name=f"concentration_link_{i}_{j}_{g}")
       if alloc_domain=="integer":model.addConstr(alloc>=use[j,g,i],name=f"concentration_support_{i}_{j}_{g}")
       if x_vars is not None:model.addConstr(use[j,g,i]<=x_vars[i,j,final],name=f"concentration_x_{i}_{j}_{g}")
      for var in use.values():var.BranchPriority=25
    raw=gp.quicksum(use.values()) if active else 0.0
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","use_vars":use,"raw_used_bays":raw,"normalized_expression":raw/meta["scale"] if active else 0.0}

def evaluate_joint_group_concentration(data,solution,*,alloc_domain="integer",enabled=True,tolerance=1e-6):
    meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);used={};total=0
    if active:
      final=meta["final_period"]
      for j,g in meta["positive_ship_groups"]:
       used[j,g]=[i for i in meta["feasible_bays"][j,g] if float(solution.get("alloc_boxes",{}).get((i,j,g,final),0))>tolerance];total+=len(used[j,g])
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","used_bays":used,"used_bays_total":total if active else None,"raw_used_bays":total if active else None,"normalized":None if not active else total/meta["scale"]}

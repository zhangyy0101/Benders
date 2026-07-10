"""Canonical joint ship-group block-concentration formulation and evaluator."""
from __future__ import annotations
import gurobipy as gp
from gurobipy import GRB
from model_common import group_size, groups, remaining_capacity, required_reserve

TOL=1e-9
def has_joint_attribute_groups(data):
    if "adapted" in data.get("ScenarioName","") or "synthetic_yard" in data.get("ScenarioName",""):return False
    G=list(data.get("G") or []);attrs=data.get("GroupAttrs",{});arr=data.get("Arrivals_group_interval",{})
    if not G or any(g not in attrs or g not in data.get("GroupSize",{}) for g in G):return False
    if any(any(str(attrs[g].get(a,"ALL")).upper() in {"","ALL","NONE"} for a in ("pod","height","weight_class")) for g in G):return False
    return all((j,g,n) in arr for j in data["J_new"] for g in G for n in data["N"])

def concentration_metadata(data,alloc_domain="integer"):
    available=has_joint_attribute_groups(data);final=max(data["N"]);rem=remaining_capacity(data);positive=[];M={};minimum={};feasible={}
    if available:
      for j in data["J_new"]:
       for g in groups(data):
        required=required_reserve(data,j,g,final,alloc_domain)
        if required<=TOL:continue
        positive.append((j,g));caps={}
        for k in data["K"]:
          cap=sum(rem[i,final] for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==group_size(data,g));caps[k]=max(0,min(required,cap));M[j,g,k]=caps[k]
        feasible[j,g]=[k for k,v in caps.items() if v>TOL];running=0;L=0
        for value in sorted((caps[k] for k in feasible[j,g]),reverse=True):running+=value;L+=1
        minimum[j,g]=next((q for q in range(1,len(feasible[j,g])+1) if sum(sorted((caps[k] for k in feasible[j,g]),reverse=True)[:q])>=required-TOL),len(feasible[j,g])+1)
    scale=max(1,sum(max(0,len(feasible[p])-minimum[p]) for p in positive))
    return {"available":available,"final_period":final,"positive_ship_groups":positive,"big_m":M,"minimum_blocks":minimum,"feasible_blocks":feasible,"scale":scale}

def build_joint_group_concentration(model,data,alloc_vars,*,alloc_domain="integer",enabled=True,x_vars=None,relax=False):
    relax=relax or model.ModelName.endswith("_lp");meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);use={}
    if active:
      use=model.addVars([(j,g,k) for j,g in meta["positive_ship_groups"] for k in data["K"]],lb=0,ub=1,vtype=GRB.CONTINUOUS if relax else GRB.BINARY,name="joint_group_block_use")
      final=meta["final_period"]
      for j,g in meta["positive_ship_groups"]:
       for k in data["K"]:
        M=meta["big_m"][j,g,k]
        if M<=TOL:use[j,g,k].UB=0
        else:
         block_alloc=gp.quicksum(alloc_vars[i,j,g,final] for i in data["Bays_in_Block"][k]);model.addConstr(block_alloc<=M*use[j,g,k],name=f"concentration_link_{j}_{g}_{k}")
         if alloc_domain=="integer":model.addConstr(block_alloc>=use[j,g,k],name=f"concentration_support_{j}_{g}_{k}")
         if x_vars is not None:model.addConstr(use[j,g,k]<=gp.quicksum(x_vars[i,j,final] for i in data["Bays_in_Block"][k]),name=f"concentration_x_{j}_{g}_{k}")
       model.addConstr(gp.quicksum(use[j,g,k] for k in data["K"])>=meta["minimum_blocks"][j,g],name=f"concentration_min_blocks_{j}_{g}")
       model.addConstr(gp.quicksum(meta["big_m"][j,g,k]*use[j,g,k] for k in data["K"])>=required_reserve(data,j,g,final,alloc_domain),name=f"concentration_cover_{j}_{g}")
      for var in use.values():var.BranchPriority=25
    raw=gp.quicksum(use[j,g,k] for j,g in meta["positive_ship_groups"] for k in data["K"])-sum(meta["minimum_blocks"].values()) if active else 0.0
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","use_vars":use,"raw_excess_blocks":raw,"normalized_expression":raw/meta["scale"] if active else 0.0}

def evaluate_joint_group_concentration(data,solution,*,alloc_domain="integer",enabled=True,tolerance=1e-6):
    meta=concentration_metadata(data,alloc_domain);active=bool(enabled and meta["available"]);used={};total=0
    if active:
      final=meta["final_period"]
      for j,g in meta["positive_ship_groups"]:
       used[j,g]=[k for k in data["K"] if sum(float(solution.get("alloc_boxes",{}).get((i,j,g,final),0)) for i in data["Bays_in_Block"][k])>tolerance];total+=len(used[j,g])
    raw=sum(len(used[p])-meta["minimum_blocks"][p] for p in meta["positive_ship_groups"]) if active else None
    return {**meta,"enabled":active,"status":"ENABLED" if active else "NOT_APPLICABLE" if not meta["available"] else "DISABLED","used_blocks":used,"used_blocks_total":total if active else None,"minimum_required_blocks_total":sum(meta["minimum_blocks"].values()) if active else None,"raw_excess_blocks":raw,"normalized":None if raw is None else raw/meta["scale"]}

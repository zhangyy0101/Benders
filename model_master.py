"""High-level Route-B master: open decisions, reserve decisions and eta only."""
from __future__ import annotations
import gurobipy as gp
from gurobipy import GRB
from model_common import group_attr,group_size,groups,remaining_capacity,required_reserve,scale_factor,ship_groups,ship_group_pairs
from model_concentration import build_joint_group_concentration

def build_master_model(data,weights,*,alloc_domain="integer",relax=False,cut_pool=None,redundant_block_binary=False,concentration_enabled=True):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};binary=GRB.CONTINUOUS if relax else GRB.BINARY;avt=GRB.CONTINUOUS if relax or alloc_domain=="continuous" else GRB.INTEGER;m=gp.Model("route_b_master_lp" if relax else "route_b_master");m.Params.OutputFlag=0
    pairs=ship_group_pairs(data);alloc=m.addVars([(i,j,g,n) for i in I for j,g in pairs for n in N],lb=0,vtype=avt,name="alloc_boxes");heights=list(data.get("HeightTypes",["STD","HIGH"]));bay_height=m.addVars(I,heights,lb=0,ub=1,vtype=binary,name="bay_height");block=m.addVars(J,K,N,lb=0,ub=1,vtype=binary,name="block_use") if redundant_block_binary else {};eta=m.addVar(lb=0,name="eta")
    for i in I:
     m.addConstr(gp.quicksum(bay_height[i,h] for h in heights)<=1,name=f"single_height_{i}");old=data.get("OldBayHeight",{}).get(i)
     if old is not None:m.addConstr(bay_height[i,old]==1,name=f"old_height_{i}_{old}")
    for i in I:
     for n in N:
      m.addConstr(gp.quicksum(alloc[i,j,g,n] for j,g in pairs)<=rem[i,n],name=f"bay_capacity_{i}_{n}")
      for j in J:
       if n>0:
        for g in ship_groups(data,j):m.addConstr(alloc[i,j,g,n]>=alloc[i,j,g,n-1],name=f"alloc_mono_{i}_{j}_{g}_{n}")
      for j,g in pairs:
       if group_size(data,g)!=modes[i]:m.addConstr(alloc[i,j,g,n]==0,name=f"mode_{i}_{j}_{g}_{n}")
       else:m.addConstr(alloc[i,j,g,n]<=rem[i,n]*bay_height[i,group_attr(data,g,"height")],name=f"height_{i}_{j}_{g}_{n}")
    for j in J:
     for g in ship_groups(data,j):
      for n in N:m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)==required_reserve(data,j,g,n,alloc_domain),name=f"exact_reserve_{j}_{g}_{n}")
     if redundant_block_binary:
      for k in K:
       bays=data["Bays_in_Block"][k]
       for n in N:
        reserved=gp.quicksum(alloc[i,j,g,n] for i in bays for g in ship_groups(data,j))
        m.addConstr(reserved<=sum(rem[i,n] for i in bays)*block[j,k,n])
        m.addConstr(block[j,k,n]<=reserved)
    concentration=build_joint_group_concentration(m,data,alloc,alloc_domain=alloc_domain,enabled=concentration_enabled and weights.master.concentration>0);open_expr=gp.LinExpr(0.0);concentration_expr=scale_factor(weights)*weights.master.concentration*concentration["normalized_expression"];m.setObjective(concentration_expr+eta,GRB.MINIMIZE)
    for var in block.values():var.BranchPriority=30
    for var in alloc.values():var.BranchPriority=5
    vars={"alloc_boxes":alloc,"eta":eta,"bay_height":bay_height}
    if concentration["enabled"]:vars["concentration_use"]=concentration["use_vars"]
    if redundant_block_binary:vars["block_use"]=block
    if cut_pool:
     for record in cut_pool.records:m.addConstr(record.as_expression(vars)>=0,name=f"inherited_{record.signature[:12]}")
    m.update();return m,vars,{"open_expression":open_expr,"concentration_expression":concentration_expr,"concentration_raw_expression":concentration["raw_used_bays"],"concentration_scale":concentration["scale"],"concentration_context":concentration,"remaining_capacity":rem}
def extract_master_point(vars,get_value=lambda v:v.X):
    point={"alloc_boxes":{k:float(get_value(v)) for k,v in vars["alloc_boxes"].items()},"eta":float(get_value(vars["eta"]))}
    if "concentration_use" in vars:point["concentration_use"]={k:float(get_value(v)) for k,v in vars["concentration_use"].items()}
    return point

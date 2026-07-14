"""High-level Route-B master: open decisions, reserve decisions and eta only."""
from __future__ import annotations
import gurobipy as gp
from gurobipy import GRB
from model_common import add_common_master_valid_inequalities,group_size,groups,objective_scales,remaining_capacity,required_reserve,scale_factor,ship_groups,ship_group_pairs
from model_aggregate_recourse_lb import add_aggregate_recourse_relaxation
from model_concentration import build_joint_group_concentration

def build_master_model(data,weights,*,alloc_domain="integer",relax=False,add_valid_inequalities=True,valid_inequality_profile="common",cut_pool=None,aggregate_recourse_lb=True,aggregate_relaxation_level="size",analytic_recourse_lb=True,redundant_block_binary=False,concentration_enabled=True):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];alpha=float(data["Alpha"]);rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};binary=GRB.CONTINUOUS if relax else GRB.BINARY;avt=GRB.CONTINUOUS if relax or alloc_domain=="continuous" else GRB.INTEGER;m=gp.Model("route_b_master_lp" if relax else "route_b_master");m.Params.OutputFlag=0
    pairs=ship_group_pairs(data);x=m.addVars(I,J,N,lb=0,ub=1,vtype=binary,name="x");alloc=m.addVars([(i,j,g,n) for i in I for j,g in pairs for n in N],lb=0,vtype=avt,name="alloc_boxes");block=m.addVars(J,K,N,lb=0,ub=1,vtype=binary,name="block_use") if redundant_block_binary else {};eta=m.addVar(lb=0,name="eta")
    for i in I:
     for n in N:
      m.addConstr(gp.quicksum(alloc[i,j,g,n] for j,g in pairs)<=rem[i,n],name=f"bay_capacity_{i}_{n}")
      for j in J:
       jg=ship_groups(data,j);m.addConstr(gp.quicksum(alloc[i,j,g,n] for g in jg)<=rem[i,n]*x[i,j,n],name=f"alloc_x_{i}_{j}_{n}");m.addConstr(x[i,j,n]<=gp.quicksum(alloc[i,j,g,n] for g in jg),name=f"x_alloc_{i}_{j}_{n}")
       if n>0:
        for g in ship_groups(data,j):m.addConstr(alloc[i,j,g,n]>=alloc[i,j,g,n-1],name=f"alloc_mono_{i}_{j}_{g}_{n}")
      for j,g in pairs:
       if group_size(data,g)!=modes[i]:m.addConstr(alloc[i,j,g,n]==0,name=f"mode_{i}_{j}_{g}_{n}")
    for j in J:
     for g in ship_groups(data,j):
      for n in N:m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)==required_reserve(data,j,g,n,alloc_domain),name=f"exact_reserve_{j}_{g}_{n}")
     if redundant_block_binary:
      for k in K:
       bays=data["Bays_in_Block"][k]
       for n in N:m.addConstr(gp.quicksum(x[i,j,n] for i in bays)<=len(bays)*block[j,k,n]);m.addConstr(block[j,k,n]<=gp.quicksum(x[i,j,n] for i in bays))
    valid=add_common_master_valid_inequalities(m,data,{"x":x,"alloc_boxes":alloc},enabled=add_valid_inequalities,profile=valid_inequality_profile)
    concentration=build_joint_group_concentration(m,data,alloc,alloc_domain=alloc_domain,enabled=concentration_enabled and weights.master.concentration>0,x_vars=x);scales=objective_scales(data);open_expr=scale_factor(weights)*weights.master.x*gp.quicksum(x[i,j,n]*float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N)/scales["open"];concentration_expr=scale_factor(weights)*weights.master.concentration*concentration["normalized_expression"];m.setObjective(open_expr+concentration_expr+eta,GRB.MINIMIZE)
    aggregate=add_aggregate_recourse_relaxation(m,data,weights,x,alloc,eta,enabled=aggregate_recourse_lb,level=aggregate_relaxation_level,analytic_enabled=analytic_recourse_lb)
    for var in block.values():var.BranchPriority=30
    for var in x.values():var.BranchPriority=30
    for var in alloc.values():var.BranchPriority=5
    vars={"x":x,"alloc_boxes":alloc,"eta":eta}
    if concentration["enabled"]:vars["concentration_use"]=concentration["use_vars"]
    if redundant_block_binary:vars["block_use"]=block
    if cut_pool:
     for record in cut_pool.records:m.addConstr(record.as_expression(vars)>=0,name=f"inherited_{record.signature[:12]}")
    m.update();strengthening={"aggregate_enabled":bool(aggregate_recourse_lb),"aggregate_level":aggregate_relaxation_level,"aggregate_variable_count":aggregate["variable_count"],"aggregate_constraint_count":aggregate["constraint_count"],"aggregate_build_time":aggregate["build_time"],"valid_inequalities_enabled":bool(add_valid_inequalities),"valid_inequality_profile":valid["profile"],"valid_inequality_count_by_family":valid["count_by_family"],"valid_inequality_constraint_count":valid["count"],"valid_inequality_build_time":valid["build_time"]};return m,vars,{"open_expression":open_expr,"concentration_expression":concentration_expr,"concentration_raw_expression":concentration["raw_used_bays"],"concentration_scale":concentration["scale"],"concentration_context":concentration,"remaining_capacity":rem,"aggregate":aggregate,"master_strengthening":strengthening}
def extract_master_point(vars,get_value=lambda v:v.X):
    point={"x":{k:float(get_value(v)) for k,v in vars["x"].items()},"alloc_boxes":{k:float(get_value(v)) for k,v in vars["alloc_boxes"].items()},"eta":float(get_value(vars["eta"]))}
    if "concentration_use" in vars:point["concentration_use"]={k:float(get_value(v)) for k,v in vars["concentration_use"].items()}
    return point

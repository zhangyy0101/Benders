"""High-level Route-B master: open decisions, reserve decisions and eta only."""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB
from model_common import arrival,group_size,groups,objective_scales,remaining_capacity,scale_factor

def build_master_model(data,weights,*,alloc_domain="integer",relax=False,add_valid_inequalities=True,cut_pool=None):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];alpha=float(data["Alpha"]);rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};binary=GRB.CONTINUOUS if relax else GRB.BINARY;avt=GRB.CONTINUOUS if relax or alloc_domain=="continuous" else GRB.INTEGER;m=gp.Model("route_b_master_lp" if relax else "route_b_master");m.Params.OutputFlag=0
    x=m.addVars(I,J,N,lb=0,ub=1,vtype=binary,name="x");alloc=m.addVars(I,J,G,N,lb=0,vtype=avt,name="alloc_boxes");block=m.addVars(J,K,N,lb=0,ub=1,vtype=binary,name="block_use");eta=m.addVar(lb=0,name="eta")
    for i in I:
     for n in N:
      m.addConstr(gp.quicksum(alloc[i,j,g,n] for j in J for g in G)<=rem[i,n],name=f"bay_capacity_{i}_{n}")
      for j in J:
       m.addConstr(gp.quicksum(alloc[i,j,g,n] for g in G)<=rem[i,n]*x[i,j,n],name=f"alloc_x_{i}_{j}_{n}");m.addConstr(x[i,j,n]<=gp.quicksum(alloc[i,j,g,n] for g in G),name=f"x_alloc_{i}_{j}_{n}")
       if n>0:
        for g in G:m.addConstr(alloc[i,j,g,n]>=alloc[i,j,g,n-1],name=f"alloc_mono_{i}_{j}_{g}_{n}")
      for g in G:
       if group_size(data,g)!=modes[i]:m.addConstr(gp.quicksum(alloc[i,j,g,n] for j in J)==0,name=f"mode_{i}_{g}_{n}")
    for j in J:
     for g in G:
      cumulative=0
      for n in N:cumulative+=arrival(data,j,g,n);m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)>=alpha*cumulative,name=f"reserve_{j}_{g}_{n}")
     for k in K:
      bays=data["Bays_in_Block"][k]
      for n in N:m.addConstr(gp.quicksum(x[i,j,n] for i in bays)<=len(bays)*block[j,k,n]);m.addConstr(block[j,k,n]<=gp.quicksum(x[i,j,n] for i in bays))
     if add_valid_inequalities:
      for size in data["S"]:
       bays=[i for i in I if modes[i]==int(size)];sg=[g for g in G if group_size(data,g)==int(size)]
       for n in N:
        need=sum(arrival(data,j,g,n) for g in sg);caps=[float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"]) for i in bays];maxcap=max(caps,default=0)
        if need>1e-9:m.addConstr(gp.quicksum(caps[p]*x[i,j,n] for p,i in enumerate(bays))>=alpha*need,name=f"handling_necessary_{j}_{size}_{n}")
        if need>1e-9 and maxcap>0:m.addConstr(gp.quicksum(x[i,j,n] for i in bays)>=math.ceil(alpha*need/maxcap-1e-9),name=f"min_bays_{j}_{size}_{n}")
    if add_valid_inequalities and not any(float(v)>1e-9 for v in data.get("New_Outbound_Req",{}).values()):
     for n in N[1:]:
      for j in J:
       for i in I:m.addConstr(x[i,j,n]>=x[i,j,n-1],name=f"x_mono_{i}_{j}_{n}")
       for k in K:m.addConstr(block[j,k,n]>=block[j,k,n-1],name=f"block_mono_{j}_{k}_{n}")
    scales=objective_scales(data);open_expr=scale_factor(weights)*weights.master.x*gp.quicksum(x[i,j,n]*float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N)/scales["open"];m.setObjective(open_expr+eta,GRB.MINIMIZE)
    for var in block.values():var.BranchPriority=30
    for var in x.values():var.BranchPriority=20
    for var in alloc.values():var.BranchPriority=5
    vars={"x":x,"alloc_boxes":alloc,"block_use":block,"eta":eta}
    if cut_pool:
     for record in cut_pool.records:m.addConstr(record.as_expression(vars)>=0,name=f"inherited_{record.signature[:12]}")
    m.update();return m,vars,{"open_expression":open_expr,"remaining_capacity":rem}
def extract_master_point(vars,get_value=lambda v:v.X):return {"x":{k:float(get_value(v)) for k,v in vars["x"].items()},"alloc_boxes":{k:float(get_value(v)) for k,v in vars["alloc_boxes"].items()},"eta":float(get_value(vars["eta"]))}

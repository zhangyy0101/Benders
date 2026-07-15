"""Group-aggregated master for partial branch-and-Benders-cut."""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB
from model_common import arrival,fixed_in_block,group_attr,group_size,objective_scales,outbound_pressure,remaining_capacity,required_reserve,scale_factor,ship_group_pairs,ship_groups

def build_partial_master(data,weights,*,relax=False,alloc_domain="integer",concentration_enabled=True):
    m=gp.Model("group_aggregated_partial_master");m.Params.OutputFlag=0;K,N,I=data["K"],data["N"],data["I_list"];pairs=[(j,g) for j,g in ship_group_pairs(data) if required_reserve(data,j,g,max(N),alloc_domain)>0];rem=remaining_capacity(data);binary=GRB.CONTINUOUS if relax else GRB.BINARY;integer=GRB.CONTINUOUS if relax else GRB.INTEGER
    a_indices=[(k,j,g,n) for j,g in pairs for k in K for n in N];A=m.addVars(a_indices,lb=0,vtype=integer,name="block_alloc");z=m.addVars([(j,k,g,n) for j,g in pairs for k in K for n in N],lb=0,name="block_flow");bits={}
    for key in a_indices:
        k,j,g,n=key;upper=int(required_reserve(data,j,g,n,alloc_domain));width=max(1,upper.bit_length())
        for b in range(width):bits[key,b]=m.addVar(lb=0,ub=1,vtype=binary,name=f"alloc_bit_{k}_{j}_{g}_{n}_{b}")
        m.addConstr(A[key]==gp.quicksum((1<<b)*bits[key,b] for b in range(width)),name=f"alloc_binary_expansion_{k}_{j}_{g}_{n}")
    heights=list(data.get("HeightTypes",["STD","HIGH"]));y=m.addVars(I,heights,lb=0,ub=1,vtype=binary,name="bay_height")
    ship_pods=[(j,p) for j in data["J_new"] for p in sorted({group_attr(data,g,"pod") for g in ship_groups(data,j) if required_reserve(data,j,g,max(N),alloc_domain)>0})]
    support=m.addVars([(j,p,h,i) for j,p in ship_pods for h in heights for i in I],lb=0,ub=1,vtype=binary,name="pod_height_bay_support");used=m.addVars([(j,p,i) for j,p in ship_pods for i in I],lb=0,ub=1,vtype=binary,name="ship_pod_bay_use")
    for i in I:
        m.addConstr(gp.quicksum(y[i,h] for h in heights)<=1,name=f"one_height_{i}");old=data.get("OldBayHeight",{}).get(i)
        if old is not None:m.addConstr(y[i,old]==1,name=f"old_height_{i}_{old}")
    for j,p in ship_pods:
      for i in I:
        for h in heights:m.addConstr(support[j,p,h,i]<=y[i,h]);m.addConstr(used[j,p,i]>=support[j,p,h,i])
        m.addConstr(used[j,p,i]<=gp.quicksum(support[j,p,h,i] for h in heights))
    for j,g in pairs:
      p,h=group_attr(data,g,"pod"),group_attr(data,g,"height");s=group_size(data,g)
      for n in N:
        m.addConstr(gp.quicksum(A[k,j,g,n] for k in K)==required_reserve(data,j,g,n,alloc_domain),name=f"reserve_{j}_{g}_{n}");m.addConstr(gp.quicksum(z[j,k,g,n] for k in K)==arrival(data,j,g,n),name=f"arrival_{j}_{g}_{n}")
        for k in K:
          if n>min(N):m.addConstr(A[k,j,g,n]>=A[k,j,g,n-1],name=f"mono_{k}_{j}_{g}_{n}")
          m.addConstr(gp.quicksum(z[j,k,g,t] for t in N if t<=n)<=A[k,j,g,n],name=f"storage_{k}_{j}_{g}_{n}")
          eligible=[i for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==s]
          m.addConstr(A[k,j,g,n]<=gp.quicksum(math.floor(rem[i,n]+1e-9)*support[j,p,h,i] for i in eligible),name=f"support_capacity_{k}_{j}_{g}_{n}")
    for k in K:
      for n in N:
        for s in data["S"]:m.addConstr(gp.quicksum(A[k,j,g,n] for j,g in pairs if group_size(data,g)==int(s))<=sum(math.floor(rem[i,n]+1e-9) for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==int(s)),name=f"block_size_cap_{k}_{s}_{n}")
    total=m.addVars(K,N,lb=0,name="agg_total");avg=m.addVars(N,lb=0,name="agg_avg");bal=m.addVars(K,N,lb=0,name="agg_bal");fixed=fixed_in_block(data)
    for k in K:
      for n in N:m.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(z[j,k,g,n] for j,g in pairs));m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
    for n in N:m.addConstr(len(K)*avg[n]==gp.quicksum(total[k,n] for k in K))
    sc=objective_scales(data);factor=scale_factor(weights);pressure=outbound_pressure(data);con=factor*weights.master.concentration*gp.quicksum(used.values())/max(1,len(ship_pods)) if concentration_enabled else 0;rec=factor*(weights.sub.dist*gp.quicksum(float(data["Dist"][j,k])*z[j,k,g,n] for j,g in pairs for k in K for n in N)/sc["distance"]+weights.sub.balance*bal.sum()/sc["balance"]+weights.sub.conflict*gp.quicksum(float(pressure[k,n])*z[j,k,g,n] for j,g in pairs for k in K for n in N)/sc["conflict"]);m.setObjective(con+rec);m.update();return m,{"block_alloc":A,"allocation_bits":bits,"block_flow":z,"bay_height":y,"pod_support":support,"concentration_use":used,"in_total":total,"avg":avg,"g_bal":bal},{"concentration":con,"recourse":rec,"ship_pods":ship_pods,"remaining_capacity":rem}

def extract_partial_point(vars,get=lambda v:v.X):return {name:{k:float(get(v)) for k,v in values.items()} for name,values in vars.items()}

"""POD-demand master; size and height are explicit demand parameters, not groups."""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB
from model_common import demand_types,fixed_in_block,objective_scales,outbound_pressure,remaining_capacity,scale_factor,type_arrival,type_reserve

def build_partial_master(data,weights,*,relax=False,alloc_domain="integer",concentration_enabled=True):
 m=gp.Model("pod_size_height_partial_master");m.Params.OutputFlag=0;K,N,I=data["K"],data["N"],data["I_list"];types=demand_types(data);rem=remaining_capacity(data);iv=GRB.CONTINUOUS if relax else GRB.INTEGER;bv=GRB.CONTINUOUS if relax else GRB.BINARY
 idx=[(k,j,p,s,h,n) for j,p,s,h in types for k in K for n in N];A=m.addVars(idx,lb=0,vtype=iv,name="block_alloc");z=m.addVars([(j,k,p,s,h,n) for j,p,s,h in types for k in K for n in N],lb=0,name="block_flow");bits={}
 for key in idx:
  k,j,p,s,h,n=key;upper=int(type_reserve(data,j,p,s,h,n,alloc_domain));width=max(1,upper.bit_length())
  for b in range(width):bits[key,b]=m.addVar(vtype=bv,name=f"alloc_bit_{k}_{j}_{p}_{s}_{h}_{n}_{b}")
  m.addConstr(A[key]==gp.quicksum((1<<b)*bits[key,b] for b in range(width)))
 heights=list(data.get("HeightTypes",["STD","HIGH"]));y=m.addVars(I,heights,vtype=bv,name="bay_height");ship_pods=sorted({(j,p) for j,p,s,h in types});support=m.addVars([(j,p,h,i) for j,p in ship_pods for h in heights for i in I],vtype=bv);used=m.addVars([(j,p,i) for j,p in ship_pods for i in I],vtype=bv)
 for i in I:
  m.addConstr(y.sum(i,"*")<=1);old=data.get("OldBayHeight",{}).get(i)
  if old is not None:m.addConstr(y[i,old]==1)
 for j,p in ship_pods:
  for i in I:
   for h in heights:m.addConstr(support[j,p,h,i]<=y[i,h]);m.addConstr(used[j,p,i]>=support[j,p,h,i])
   m.addConstr(used[j,p,i]<=gp.quicksum(support[j,p,h,i] for h in heights))
 for j,p,s,h in types:
  for n in N:
   m.addConstr(gp.quicksum(A[k,j,p,s,h,n] for k in K)==type_reserve(data,j,p,s,h,n,alloc_domain));m.addConstr(gp.quicksum(z[j,k,p,s,h,n] for k in K)==type_arrival(data,j,p,s,h,n))
   for k in K:
    if n>min(N):m.addConstr(A[k,j,p,s,h,n]>=A[k,j,p,s,h,n-1])
    m.addConstr(gp.quicksum(z[j,k,p,s,h,t] for t in N if t<=n)<=A[k,j,p,s,h,n]);eligible=[i for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==s]
    m.addConstr(A[k,j,p,s,h,n]<=gp.quicksum(math.floor(rem[i,n]+1e-9)*support[j,p,h,i] for i in eligible))
 for k in K:
  for n in N:
   for s in map(int,data["S"]):m.addConstr(gp.quicksum(A[k,j,p,ss,h,n] for j,p,ss,h in types if ss==s)<=sum(math.floor(rem[i,n]+1e-9) for i in data["Bays_in_Block"][k] if int(data["Fixed_Bay_Mode"][i])==s))
 total=m.addVars(K,N,lb=0);avg=m.addVars(N,lb=0);bal=m.addVars(K,N,lb=0);fixed=fixed_in_block(data)
 for k in K:
  for n in N:m.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(z[j,k,p,s,h,n] for j,p,s,h in types));m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
 for n in N:m.addConstr(len(K)*avg[n]==total.sum("*",n))
 sc=objective_scales(data);f=scale_factor(weights);pr=outbound_pressure(data);con=f*weights.master.concentration*gp.quicksum(used.values())/max(1,len(ship_pods)) if concentration_enabled else 0;rec=f*(weights.sub.dist*gp.quicksum(float(data["Dist"][j,k])*z[j,k,p,s,h,n] for j,p,s,h in types for k in K for n in N)/sc["distance"]+weights.sub.balance*bal.sum()/sc["balance"]+weights.sub.conflict*gp.quicksum(float(pr[k,n])*z[j,k,p,s,h,n] for j,p,s,h in types for k in K for n in N)/sc["conflict"]);m.setObjective(con+rec);m.update();return m,{"block_alloc":A,"allocation_bits":bits,"block_flow":z,"bay_height":y,"pod_support":support,"concentration_use":used,"in_total":total,"avg":avg,"g_bal":bal},{"concentration":con,"recourse":rec,"ship_pods":ship_pods,"remaining_capacity":rem,"demand_types":types}

def extract_partial_point(vars,get=lambda v:v.X):return {name:{k:float(get(v)) for k,v in values.items()} for name,values in vars.items()}

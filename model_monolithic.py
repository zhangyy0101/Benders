"""Complete sparse monolithic formulation shared by direct solve and ALNS."""
from __future__ import annotations
import gurobipy as gp
from gurobipy import GRB
from model_common import arrival,fixed_in_block,group_attr,group_size,objective_scales,outbound_pressure,remaining_capacity,required_reserve,scale_factor,ship_group_pairs,ship_groups
from model_concentration import build_joint_group_concentration

def build_monolithic_model(data,weights,*,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True):
 I,J,N,K=data["I_list"],data["J_new"],data["N"],data["K"];pairs=ship_group_pairs(data);rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};vt=GRB.INTEGER if alloc_domain=="integer" else GRB.CONTINUOUS;m=gp.Model("route_b_monolithic");m.Params.OutputFlag=0
 alloc=m.addVars([(i,j,g,n) for i in I for j,g in pairs for n in N],lb=0,vtype=vt,name="alloc_boxes");heights=list(data.get("HeightTypes",["STD","HIGH"]));bay_height=m.addVars(I,heights,vtype=GRB.BINARY,name="bay_height");din=m.addVars([(j,g,i,n) for j,g in pairs for i in I for n in N],lb=0,name="din");share=m.addVars([(j,k,g,n) for j,g in pairs for k in K for n in N],lb=0,name="in_share");total=m.addVars(K,N,lb=0,name="in_total");avg=m.addVars(N,lb=0,name="avg");bal=m.addVars(K,N,lb=0,name="g_bal")
 for i in I:
  m.addConstr(gp.quicksum(bay_height[i,h] for h in heights)<=1,name=f"single_height_{i}");old=data.get("OldBayHeight",{}).get(i)
  if old is not None:m.addConstr(bay_height[i,old]==1,name=f"old_height_{i}_{old}")
 for i in I:
  for n in N:
   m.addConstr(gp.quicksum(alloc[i,j,g,n] for j,g in pairs)<=rem[i,n],name=f"bay_capacity_{i}_{n}")
   for j,g in pairs:m.addConstr(alloc[i,j,g,n]<=rem[i,n]*bay_height[i,group_attr(data,g,"height")],name=f"height_{i}_{j}_{g}_{n}")
   for j in J:
    gs=ship_groups(data,j)
    if n>0:
     for g in gs:m.addConstr(alloc[i,j,g,n]>=alloc[i,j,g,n-1],name=f"alloc_mono_{i}_{j}_{g}_{n}")
   for j,g in pairs:
    if group_size(data,g)!=modes[i]:m.addConstr(alloc[i,j,g,n]==0,name=f"mode_{i}_{j}_{g}_{n}")
 for j,g in pairs:
  for n in N:
   m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)==required_reserve(data,j,g,n,alloc_domain),name=f"exact_reserve_{j}_{g}_{n}");m.addConstr(gp.quicksum(din[j,g,i,n] for i in I)==arrival(data,j,g,n),name=f"arrival_{j}_{g}_{n}")
   for i in I:
    initial=float(data["initial_inventory_data"].get((i,j,g),0));m.addConstr(initial+gp.quicksum(din[j,g,i,t] for t in N if t<=n)<=alloc[i,j,g,n],name=f"storage_{i}_{j}_{g}_{n}")
 for j in J:
  gs=ship_groups(data,j)
  for k in K:
   for n in N:
    for g in gs:m.addConstr(share[j,k,g,n]==gp.quicksum(din[j,g,i,n] for i in data["Bays_in_Block"][k]),name=f"share_{j}_{k}_{g}_{n}")
 fixed=fixed_in_block(data)
 for k in K:
  for n in N:m.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(share[j,k,g,n] for j,g in pairs),name=f"total_{k}_{n}");m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
 for n in N:m.addConstr(len(K)*avg[n]==gp.quicksum(total[k,n] for k in K))
 concentration=build_joint_group_concentration(m,data,alloc,alloc_domain=alloc_domain,enabled=concentration_enabled and weights.master.concentration>0);sc=objective_scales(data);pressure=outbound_pressure(data);open_raw=gp.LinExpr(0.0);open_obj=gp.LinExpr(0.0);concentration_obj=scale_factor(weights)*weights.master.concentration*concentration["normalized_expression"];dist=gp.quicksum(float(data["Dist"][j,k])*share[j,k,g,n] for j,g in pairs for k in K for n in N);balance=bal.sum();conflict=gp.quicksum(float(pressure[k,n])*share[j,k,g,n] for j,g in pairs for k in K for n in N);recourse=scale_factor(weights)*(weights.sub.dist*dist/sc["distance"]+weights.sub.balance*balance/sc["balance"]+weights.sub.conflict*conflict/sc["conflict"]);core=concentration_obj+recourse;m.setObjective(core,GRB.MINIMIZE);m.update();variables={"alloc_boxes":alloc,"bay_height":bay_height,"din":din,"in_share":share,"in_total":total,"avg":avg,"g_bal":bal}
 if concentration["enabled"]:variables["concentration_use"]=concentration["use_vars"]
 return m,variables,{"core_objective":core,"first_stage_objective":open_obj+concentration_obj,"open_objective":open_obj,"concentration_objective":concentration_obj,"recourse_objective":recourse,"open_raw":open_raw,"remaining_capacity":rem,"concentration_context":concentration}
def extract_solution(vars,data=None):
 solution={name:{k:float(v.X) for k,v in values.items()} for name,values in vars.items()};alloc=solution["alloc_boxes"];din=solution["din"]
 if data is not None:
  from model_common import derive_activation,reconstruct_inventory
  solution["x"]=derive_activation(data,alloc);solution["inv"]=reconstruct_inventory(data,din)
 else:
  periods=sorted({k[-1] for k in alloc});solution["x"]={(i,j,n):float(any(value>.5 for (ii,jj,g,nn),value in alloc.items() if ii==i and jj==j and nn==n)) for i,j,g,n in alloc};solution["inv"]={(j,g,i,n):sum(din.get((j,g,i,t),0.0) for t in periods if t<=n) for j,g,i,n in din}
 return solution
def evaluate_solution(data,weights,solution,*,alloc_domain="integer",concentration_enabled=True):
 from solution_evaluation import evaluate_common_solution
 return evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)

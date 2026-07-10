"""Complete monolithic formulation shared by direct solve, ALNS and validation."""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB
from model_common import arrival,fixed_in_block,group_size,groups,objective_scales,open_cost,outbound_pressure,remaining_capacity,scale_factor

def build_monolithic_model(data,weights,*,alloc_domain="integer",add_valid_inequalities=True):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];alpha=float(data["Alpha"]);rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};vt=GRB.INTEGER if alloc_domain=="integer" else GRB.CONTINUOUS;m=gp.Model("route_b_monolithic");m.Params.OutputFlag=0
    alloc=m.addVars(I,J,G,N,lb=0,vtype=vt,name="alloc_boxes");x=m.addVars(I,J,N,vtype=GRB.BINARY,name="x");block=m.addVars(J,K,N,vtype=GRB.BINARY,name="block_use");din=m.addVars(J,G,I,N,lb=0,name="din");inv=m.addVars(J,G,I,N,lb=0,name="inv");share=m.addVars(J,K,G,N,lb=0,name="in_share");total=m.addVars(K,N,lb=0,name="in_total");avg=m.addVars(N,lb=0,name="avg");bal=m.addVars(K,N,lb=0,name="g_bal")
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
      for n in N:
       cumulative+=arrival(data,j,g,n);m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)>=alpha*cumulative,name=f"reserve_{j}_{g}_{n}");m.addConstr(gp.quicksum(din[j,g,i,n] for i in I)==arrival(data,j,g,n),name=f"arrival_{j}_{g}_{n}")
       for i in I:
        previous=inv[j,g,i,n-1] if n>0 else float(data["initial_inventory_data"].get((i,j,g),0));m.addConstr(inv[j,g,i,n]==previous+din[j,g,i,n],name=f"inventory_{j}_{g}_{i}_{n}");m.addConstr(alpha*inv[j,g,i,n]<=alloc[i,j,g,n],name=f"storage_link_{i}_{j}_{g}_{n}")
     for i in I:
      for n in N:m.addConstr(alpha*gp.quicksum(din[j,g,i,n] for g in G)<=float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"])*x[i,j,n],name=f"handling_link_{i}_{j}_{n}")
     for k in K:
      for n in N:
       bays=data["Bays_in_Block"][k];m.addConstr(gp.quicksum(x[i,j,n] for i in bays)<=len(bays)*block[j,k,n],name=f"block_f_{j}_{k}_{n}");m.addConstr(block[j,k,n]<=gp.quicksum(x[i,j,n] for i in bays),name=f"block_r_{j}_{k}_{n}")
       for g in G:m.addConstr(share[j,k,g,n]==gp.quicksum(din[j,g,i,n] for i in bays),name=f"share_{j}_{k}_{g}_{n}")
    fixed=fixed_in_block(data)
    for k in K:
     for n in N:m.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(share[j,k,g,n] for j in J for g in G),name=f"total_{k}_{n}");m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
    for n in N:m.addConstr(len(K)*avg[n]==gp.quicksum(total[k,n] for k in K))
    if add_valid_inequalities and not any(float(v)>1e-9 for v in data.get("New_Outbound_Req",{}).values()):
     for n in N[1:]:
      for j in J:
       for i in I:m.addConstr(x[i,j,n]>=x[i,j,n-1])
       for k in K:m.addConstr(block[j,k,n]>=block[j,k,n-1])
    scales=objective_scales(data);pressure=outbound_pressure(data);open_raw=gp.quicksum(x[i,j,n]*float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N);dist=gp.quicksum(float(data["Dist"][j,k])*share[j,k,g,n] for j in J for k in K for g in G for n in N);balance=gp.quicksum(bal[k,n] for k in K for n in N);conflict=gp.quicksum(float(pressure[k,n])*share[j,k,g,n] for j in J for k in K for g in G for n in N);core=scale_factor(weights)*(weights.master.x*open_raw/scales["open"]+weights.sub.dist*dist/scales["distance"]+weights.sub.balance*balance/scales["balance"]+weights.sub.conflict*conflict/scales["conflict"]);m.setObjective(core,GRB.MINIMIZE);m.update();return m,{"alloc_boxes":alloc,"x":x,"block_use":block,"din":din,"inv":inv,"in_share":share,"in_total":total,"avg":avg,"g_bal":bal},{"core_objective":core,"open_raw":open_raw,"recourse_objective":core-scale_factor(weights)*weights.master.x*open_raw/scales["open"],"remaining_capacity":rem}
def extract_solution(vars):return {name:{k:float(v.X) for k,v in values.items()} for name,values in vars.items()}
def evaluate_solution(data,weights,solution):
    scales=objective_scales(data);pressure=outbound_pressure(data);G=groups(data);open_value=open_cost(data,weights,solution["x"]);distance=sum(float(data["Dist"][j,k])*solution["in_share"][j,k,g,n] for j in data["J_new"] for k in data["K"] for g in G for n in data["N"]);balance=sum(solution["g_bal"].values());conflict=sum(float(pressure[k,n])*solution["in_share"][j,k,g,n] for j in data["J_new"] for k in data["K"] for g in G for n in data["N"]);rec=scale_factor(weights)*(weights.sub.dist*distance/scales["distance"]+weights.sub.balance*balance/scales["balance"]+weights.sub.conflict*conflict/scales["conflict"]);return {"open_cost":open_value,"recourse_cost":rec,"core_cost":open_value+rec,"distance_raw":distance,"balance_raw":balance,"conflict_raw":conflict}

"""Complete monolithic formulation shared by direct solve, ALNS and validation."""
from __future__ import annotations
import math
import gurobipy as gp
from gurobipy import GRB
from model_common import add_common_master_valid_inequalities,arrival,fixed_in_block,group_size,groups,objective_scales,first_stage_cost,outbound_pressure,remaining_capacity,required_reserve,scale_factor
from model_concentration import build_joint_group_concentration

def build_monolithic_model(data,weights,*,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True):
    I,J,G,N,K=data["I_list"],data["J_new"],groups(data),data["N"],data["K"];alpha=float(data["Alpha"]);rem=remaining_capacity(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in I};vt=GRB.INTEGER if alloc_domain=="integer" else GRB.CONTINUOUS;m=gp.Model("route_b_monolithic");m.Params.OutputFlag=0
    alloc=m.addVars(I,J,G,N,lb=0,vtype=vt,name="alloc_boxes");x=m.addVars(I,J,N,vtype=GRB.BINARY,name="x");din=m.addVars(J,G,I,N,lb=0,name="din");inv=m.addVars(J,G,I,N,lb=0,name="inv");share=m.addVars(J,K,G,N,lb=0,name="in_share");total=m.addVars(K,N,lb=0,name="in_total");avg=m.addVars(N,lb=0,name="avg");bal=m.addVars(K,N,lb=0,name="g_bal")
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
      for n in N:
       m.addConstr(gp.quicksum(alloc[i,j,g,n] for i in I)==required_reserve(data,j,g,n,alloc_domain),name=f"exact_reserve_{j}_{g}_{n}");m.addConstr(gp.quicksum(din[j,g,i,n] for i in I)==arrival(data,j,g,n),name=f"arrival_{j}_{g}_{n}")
       for i in I:
        previous=inv[j,g,i,n-1] if n>0 else float(data["initial_inventory_data"].get((i,j,g),0));m.addConstr(inv[j,g,i,n]==previous+din[j,g,i,n],name=f"inventory_{j}_{g}_{i}_{n}");m.addConstr(alpha*inv[j,g,i,n]<=alloc[i,j,g,n],name=f"storage_link_{i}_{j}_{g}_{n}")
     for i in I:
      for n in N:m.addConstr(alpha*gp.quicksum(din[j,g,i,n] for g in G)<=float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"])*x[i,j,n],name=f"handling_link_{i}_{j}_{n}")
     for k in K:
      for n in N:
       bays=data["Bays_in_Block"][k]
       for g in G:m.addConstr(share[j,k,g,n]==gp.quicksum(din[j,g,i,n] for i in bays),name=f"share_{j}_{k}_{g}_{n}")
    fixed=fixed_in_block(data)
    for k in K:
     for n in N:m.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(share[j,k,g,n] for j in J for g in G),name=f"total_{k}_{n}");m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
    for n in N:m.addConstr(len(K)*avg[n]==gp.quicksum(total[k,n] for k in K))
    add_common_master_valid_inequalities(m,data,{"x":x,"alloc_boxes":alloc},enabled=add_valid_inequalities)
    concentration=build_joint_group_concentration(m,data,alloc,alloc_domain=alloc_domain,enabled=concentration_enabled and weights.master.concentration>0,x_vars=x);scales=objective_scales(data);pressure=outbound_pressure(data);open_raw=gp.quicksum(x[i,j,n]*float(data["Intervals"][n]["dur"]) for i in I for j in J for n in N);open_obj=scale_factor(weights)*weights.master.x*open_raw/scales["open"];concentration_obj=scale_factor(weights)*weights.master.concentration*concentration["normalized_expression"];dist=gp.quicksum(float(data["Dist"][j,k])*share[j,k,g,n] for j in J for k in K for g in G for n in N);balance=gp.quicksum(bal[k,n] for k in K for n in N);conflict=gp.quicksum(float(pressure[k,n])*share[j,k,g,n] for j in J for k in K for g in G for n in N);recourse=scale_factor(weights)*(weights.sub.dist*dist/scales["distance"]+weights.sub.balance*balance/scales["balance"]+weights.sub.conflict*conflict/scales["conflict"]);core=open_obj+concentration_obj+recourse;m.setObjective(core,GRB.MINIMIZE);m.update();variables={"alloc_boxes":alloc,"x":x,"din":din,"inv":inv,"in_share":share,"in_total":total,"avg":avg,"g_bal":bal};
    if concentration["enabled"]:variables["concentration_use"]=concentration["use_vars"]
    return m,variables,{"core_objective":core,"first_stage_objective":open_obj+concentration_obj,"open_objective":open_obj,"concentration_objective":concentration_obj,"recourse_objective":recourse,"open_raw":open_raw,"remaining_capacity":rem,"concentration_context":concentration}
def extract_solution(vars):return {name:{k:float(v.X) for k,v in values.items()} for name,values in vars.items()}
def evaluate_solution(data,weights,solution,*,alloc_domain="integer",concentration_enabled=True):
    """Backward-compatible thin wrapper around the canonical evaluator."""
    from solution_evaluation import evaluate_common_solution
    return evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)

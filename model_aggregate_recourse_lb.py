"""Valid analytic and size-level aggregate lower approximations of global recourse."""
from __future__ import annotations
import gurobipy as gp
from model_common import arrival,fixed_in_block,group_size,groups,objective_scales,outbound_pressure,scale_factor,ship_groups,ship_group_pairs
def analytic_recourse_lower_bounds(data,weights):
    G=groups(data);sc=objective_scales(data);factor=scale_factor(weights);distance=sum(sum(arrival(data,j,g,n) for g in G if group_size(data,g)==int(s))*min(float(data["Dist"][j,k]) for k in data["K"]) for j in data["J_new"] for s in data["S"] for n in data["N"]);pressure=outbound_pressure(data);conflict=sum(sum(arrival(data,j,g,n) for j in data["J_new"] for g in G)*min(float(pressure[k,n]) for k in data["K"]) for n in data["N"])
    m=gp.Model("analytic_balance_lb");m.Params.OutputFlag=0;flow=m.addVars(data["K"],data["N"],lb=0);total=m.addVars(data["K"],data["N"],lb=0);avg=m.addVars(data["N"],lb=0);bal=m.addVars(data["K"],data["N"],lb=0);fixed=fixed_in_block(data)
    for n in data["N"]:
      demand=sum(arrival(data,j,g,n) for j in data["J_new"] for g in G);m.addConstr(flow.sum('*',n)==demand);m.addConstr(len(data["K"])*avg[n]==total.sum('*',n))
      for k in data["K"]:m.addConstr(total[k,n]==fixed[k,n]+flow[k,n]);m.addConstr(bal[k,n]>=total[k,n]-avg[n]);m.addConstr(bal[k,n]>=avg[n]-total[k,n])
    m.setObjective(bal.sum());m.optimize();balance=float(m.ObjVal);weighted={"distance":factor*weights.sub.dist*distance/sc["distance"],"balance":factor*weights.sub.balance*balance/sc["balance"],"conflict":factor*weights.sub.conflict*conflict/sc["conflict"]};return {**weighted,"total":sum(weighted.values())}
def add_aggregate_recourse_relaxation(model,data,weights,x,alloc,eta,*,enabled=True,analytic_enabled=True):
    analytic=analytic_recourse_lower_bounds(data,weights);analytic_constr=model.addConstr(eta>=analytic["total"],name="eta_analytic_lb") if analytic_enabled else None
    if not enabled:return {"analytic":analytic,"aggregate_objective":None,"variables":{},"constraint":None}
    J,K,S,N=data["J_new"],data["K"],data["S"],data["N"];G=groups(data);modes={i:int(data["Fixed_Bay_Mode"][i]) for i in data["I_list"]};z=model.addVars(J,K,S,N,lb=0,name="agg_z");total=model.addVars(K,N,lb=0,name="agg_total");avg=model.addVars(N,lb=0,name="agg_avg");bal=model.addVars(K,N,lb=0,name="agg_bal")
    for j in J:
      for s in S:
       gs=[g for g in ship_groups(data,j) if group_size(data,g)==int(s)]
       for n in N:
        model.addConstr(gp.quicksum(z[j,k,s,n] for k in K)==sum(arrival(data,j,g,n) for g in gs),name=f"agg_arrival_{j}_{s}_{n}")
        for k in K:
         bays=[i for i in data["Bays_in_Block"][k] if modes[i]==int(s)];model.addConstr(gp.quicksum(z[j,k,s,t] for t in N if t<=n)<=gp.quicksum(alloc[i,j,g,n] for i in bays for g in gs),name=f"agg_storage_{j}_{k}_{s}_{n}")
    fixed=fixed_in_block(data);pressure=outbound_pressure(data)
    for k in K:
      for n in N:model.addConstr(total[k,n]==fixed[k,n]+gp.quicksum(z[j,k,s,n] for j in J for s in S));model.addConstr(bal[k,n]>=total[k,n]-avg[n]);model.addConstr(bal[k,n]>=avg[n]-total[k,n])
    for n in N:model.addConstr(len(K)*avg[n]==gp.quicksum(total[k,n] for k in K))
    sc=objective_scales(data);factor=scale_factor(weights);distance=factor*weights.sub.dist*gp.quicksum(float(data["Dist"][j,k])*z[j,k,s,n] for j in J for k in K for s in S for n in N)/sc["distance"];balance=factor*weights.sub.balance*gp.quicksum(bal[k,n] for k in K for n in N)/sc["balance"];conflict=factor*weights.sub.conflict*gp.quicksum(float(pressure[k,n])*z[j,k,s,n] for j in J for k in K for s in S for n in N)/sc["conflict"];obj=distance+balance+conflict;constraint=model.addConstr(eta>=obj,name="eta_aggregate_lb");return {"analytic":analytic,"aggregate_objective":obj,"distance":distance,"balance":balance,"conflict":conflict,"variables":{"z":z,"total":total,"avg":avg,"bal":bal},"constraint":constraint}

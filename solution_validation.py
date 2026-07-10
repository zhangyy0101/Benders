"""Solver-independent feasibility checks for Route-A solution dictionaries."""
from __future__ import annotations
import math
from model_common import (arrival,compute_old_occupancy,fixed_in_block,group_size,
                          new_groups,predecessor_map,required_reserve)

def validate_core_solution(data,solution,*,alloc_domain,add_valid_inequalities,tolerance=1e-5):
    I,J,G,N,K=data["I_list"],data["J_new"],new_groups(data),data["N"],data["K"]; alpha=float(data["Alpha"]); pred=predecessor_map(data); old=compute_old_occupancy(data); fixed=fixed_in_block(data); v={}
    def val(name,key): return float(solution.get(name,{}).get(key,0.0))
    def record(family,amount): v[family]=max(v.get(family,0.0),max(0.0,float(amount)))
    for j in J:
      for g in G:
       for n in N:
        record("arrival_conservation",abs(sum(val("din",(j,g,i,n)) for i in I)-arrival(data,j,g,n)))
        record("exact_required_reserve",abs(sum(val("alloc_boxes",(i,j,g,n)) for i in I)-required_reserve(data,j,g,n,alloc_domain)))
       for i in I:
        for n in N:
         previous=val("inv",(j,g,i,pred[n])) if pred[n] is not None else float(data["initial_inventory_data"].get((i,j,g),0)); inv=val("inv",(j,g,i,n)); alloc=val("alloc_boxes",(i,j,g,n)); record("inventory_balance",abs(inv-previous-val("din",(j,g,i,n))));record("inventory_nonnegativity",-inv);record("inventory_allocation",alpha*inv-alloc)
         if pred[n] is not None:record("allocation_monotonicity",val("alloc_boxes",(i,j,g,pred[n]))-alloc)
         if group_size(data,g)!=int(data["Fixed_Bay_Mode"][i]):record("fixed_bay_mode",abs(alloc))
    for i in I:
     for n in N:
      remaining=float(data["I"][i]["cap"])-old.get((i,n),0);record("storage_capacity",sum(val("alloc_boxes",(i,j,g,n)) for j in J for g in G)-remaining)
      for j in J:
       allocations=sum(val("alloc_boxes",(i,j,g,n)) for g in G); active=val("x",(i,j,n));record("allocation_activation",allocations-remaining*active);record("activation_lower_link",active-allocations); flow=sum(val("din",(j,g,i,n)) for g in G);record("handling_capacity",alpha*flow-float(data["Bay_Handling_Rate"][i,n])*float(data["Intervals"][n]["dur"])*active)
       if add_valid_inequalities and pred[n] is not None and not any(float(q)>tolerance for q in data.get("New_Outbound_Req",{}).values()):record("x_monotonicity",val("x",(i,j,pred[n]))-active)
    for j in J:
     for k in K:
      bays=data["Bays_in_Block"][k]
      for n in N:
       bu=val("block_use",(k,j,n)); sx=sum(val("x",(i,j,n)) for i in bays);record("block_use_forward",sx-len(bays)*bu);record("block_use_reverse",bu-sx)
       record("in_share_block_link",sum(val("in_share",(j,k,g,n)) for g in G)-sum(arrival(data,j,g,n) for g in G)*bu)
       if add_valid_inequalities and pred[n] is not None and not any(float(q)>tolerance for q in data.get("New_Outbound_Req",{}).values()):record("block_monotonicity",val("block_use",(k,j,pred[n]))-bu)
       for g in G:record("block_flow_equality",abs(val("in_share",(j,k,g,n))-sum(val("din",(j,g,i,n)) for i in bays)))
    for k in K:
     for n in N:
      expected=fixed[k,n]+sum(val("in_share",(j,k,g,n)) for j in J for g in G);record("in_total_definition",abs(val("in_total",(k,n))-expected));diff=val("in_total",(k,n))-val("avg",n);record("l1_positive",diff-val("g_bal",(k,n)));record("l1_negative",-diff-val("g_bal",(k,n)))
    for n in N:record("avg_definition",abs(len(K)*val("avg",n)-sum(val("in_total",(k,n)) for k in K)))
    for name in ("x","block_use"):
     for value in solution.get(name,{}).values():record("integer_residual",abs(value-round(value)))
    if alloc_domain=="integer":
     for value in solution.get("alloc_boxes",{}).values():record("integer_residual",abs(value-round(value)))
    maximum=max(v.values(),default=0.0);return {"feasible":maximum<=tolerance,"max_violation":maximum,"violations_by_family":v,"tolerance":tolerance}

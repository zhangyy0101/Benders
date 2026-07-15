"""Deterministic time-vector packing initializer for the V2 allocation model."""
from __future__ import annotations
import time
from model_common import group_attr,group_size,outbound_pressure,remaining_capacity,required_reserve,ship_group_pairs
from model_recourse import GlobalRecourseOracle
from model_common import derive_activation
from solution_evaluation import evaluate_common_solution
from solution_validation import validate_solution
from gurobipy import GRB

def build_deterministic_initial_solution(data,weights,*,alloc_domain="integer",concentration_enabled=True,add_valid_inequalities=True):
    started=time.perf_counter()
    if alloc_domain!="integer":return None
    I,N=list(data["I_list"]),list(data["N"]);pairs=ship_group_pairs(data);rem=remaining_capacity(data);pressure=outbound_pressure(data)
    compatible={(j,g):[i for i in I if int(data["Fixed_Bay_Mode"][i])==group_size(data,g) and data.get("OldBayHeight",{}).get(i,group_attr(data,g,"height"))==group_attr(data,g,"height")] for j,g in pairs};selected_height=dict(data.get("OldBayHeight",{}))
    block_of={i:next(k for k,bays in data["Bays_in_Block"].items() if i in bays) for i in I}
    load={(i,n):0 for i in I for n in N};units=[]
    def fits(i,item):return selected_height.get(i,group_attr(data,item[1],"height"))==group_attr(data,item[1],"height") and all(load[i,t]+1<=rem[i,t]+1e-9 for t in N if t>=item[2])
    def place(item,i):
        j,g,start=item
        selected_height.setdefault(i,group_attr(data,g,"height"))
        for t in N:
            if t>=start:load[i,t]+=1
        units.append([j,g,start,i])
    def remove(unit):
        for t in N:
            if t>=unit[2]:load[unit[3],t]-=1
    def bay_score(i,item):
        j,g,start=item;k=block_of[i];already=any(u[0]==j and u[1]==g and u[3]==i for u in units)
        utilization=max((load[i,t]+1)/max(rem[i,t],1e-9) for t in N if t>=start)
        return (0 if already else 1,float(data["Dist"][j,k])+.5*sum(pressure[k,t] for t in N if t>=start),utilization,str(i))
    def relocate_for(item):
        # Move one previously packed unit to expose a feasible time-capacity vector.
        for victim in sorted(units,key=lambda u:(u[2],str(u[3])),reverse=True):
            if victim[3] not in compatible[item[0],item[1]]:continue
            remove(victim)
            victim_item=(victim[0],victim[1],victim[2]);alternatives=[i for i in compatible[victim[0],victim[1]] if i!=victim[3] and fits(i,victim_item)]
            if fits(victim[3],item) and alternatives:
                old=victim[3];victim[3]=min(alternatives,key=lambda i:bay_score(i,(victim[0],victim[1],victim[2])))
                for t in N:
                    if t>=victim[2]:load[victim[3],t]+=1
                place(item,old);return True
            for t in N:
                if t>=victim[2]:load[victim[3],t]+=1
        return False
    items=[]
    for j,g in pairs:
        previous=0
        for n in N:
            current=int(round(required_reserve(data,j,g,n,"integer")))
            items.extend((j,g,n) for _ in range(current-previous));previous=current
    # Pack a group's whole time vector together to avoid concentration fragmentation.
    items.sort(key=lambda q:(len(compatible[q[0],q[1]]),-required_reserve(data,q[0],q[1],max(N),"integer"),str(q[0]),str(q[1]),q[2]))
    for item in items:
        candidates=[i for i in compatible[item[0],item[1]] if fits(i,item)]
        if candidates:place(item,min(candidates,key=lambda i:bay_score(i,item)))
        elif not relocate_for(item):return None
    alloc={(i,j,g,n):0.0 for i in I for j,g in pairs for n in N}
    for j,g,start,i in units:
        for n in N:
            if n>=start:alloc[i,j,g,n]+=1.0
    oracle=GlobalRecourseOracle(data,weights);oracle.update_rhs(alloc)
    if oracle.solve()!=GRB.OPTIMAL:return None
    solution={"x":derive_activation(data,alloc),"alloc_boxes":alloc,**oracle.solution()}
    report=validate_solution(data,solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled)
    if not report["feasible"]:return None
    evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)
    return {"solution":solution,"evaluation":evaluation,"ub":evaluation["core_cost"],"runtime":time.perf_counter()-started,"source":"deterministic_vector_packing"}

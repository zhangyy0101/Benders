"""Adaptive monolithic large-neighborhood search for Route B."""
from __future__ import annotations
import math,random,time
from gurobipy import GRB
from model_common import groups,outbound_pressure
from model_concentration import evaluate_joint_group_concentration
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution

OPERATORS=("random","active","block","interval","ship","conflict","distance","concentration")
def concentration_destroy_pool(data,solution,keys,*,alloc_domain="integer"):
    c=evaluate_joint_group_concentration(data,solution,alloc_domain=alloc_domain,enabled=True)
    if not c["enabled"]:return []
    ranked=sorted(c["positive_ship_groups"],key=lambda p:len(c["used_bays"][p]),reverse=True)
    if not ranked:return []
    j,g=ranked[0];bays=set(c["used_bays"][j,g]);return [q for q in keys if q[1]==j and q[0] in bays]
def _start(vars,solution):
    for name in ("x","alloc_boxes","din","inv","in_share"):
        for k,value in solution.get(name,{}).items():
            if name in vars and k in vars[name]:vars[name][k].Start=value
def adaptive_lns(data,weights,start_solution,*,time_limit=10,repair_time=2,repair_gap=.03,min_destroy=.1,max_destroy=.35,restarts=1,stall_iters=10,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,seed=0):
    rng=random.Random(seed);start_eval=evaluate_solution(data,weights,start_solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);current=start_solution;current_cost=start_eval["core_cost"];best=current;best_cost=current_cost;beg=time.perf_counter();log=[];stats={op:{"used":0,"accepted":0,"improved":0,"best_improved":0,"score":0.0,"weight":1.0,"runtime":0.0} for op in OPERATORS};keys=list(current["x"]);iteration=0;fraction=min_destroy;streak=0;restart_count=0;m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled);pressure=outbound_pressure(data)
    while time.perf_counter()-beg<time_limit and keys:
        iteration+=1;op=rng.choices(OPERATORS,weights=[stats[o]["weight"] for o in OPERATORS])[0];used_fraction=fraction;count=max(1,int(len(keys)*fraction));pool=keys
        if op=="active":pool=[k for k in keys if current["x"][k]>.5] or keys
        elif op=="block":
            k=rng.choice(data["K"]);pool=[q for q in keys if q[0] in data["Bays_in_Block"][k]] or keys
        elif op=="interval":
            n=rng.choice(data["N"]);pool=[q for q in keys if q[2]==n] or keys
        elif op=="ship":
            j=rng.choice(data["J_new"]);pool=[q for q in keys if q[1]==j] or keys
        elif op=="conflict":pool=sorted(keys,key=lambda q:pressure[data["I"][q[0]]["block"],q[2]]*sum(current["alloc_boxes"].get((q[0],q[1],g,q[2]),0) for g in groups(data)),reverse=True)[:max(count,len(keys)//4)] or keys
        elif op=="distance":pool=sorted(keys,key=lambda q:float(data["Dist"][q[1],data["I"][q[0]]["block"]])*sum(current["in_share"].get((q[1],data["I"][q[0]]["block"],g,q[2]),0) for g in groups(data)),reverse=True)[:max(count,len(keys)//4)] or keys
        elif op=="concentration":pool=concentration_destroy_pool(data,current,keys,alloc_domain=alloc_domain) or keys
        released=set(rng.sample(pool,min(count,len(pool))));pairs={(i,j) for i,j,_n in released}
        for var in v["x"].values():var.LB=0;var.UB=1
        for var in v["alloc_boxes"].values():var.LB=0;var.UB=GRB.INFINITY
        _start(v,current)
        for key,var in v["x"].items():
            if key not in released:var.LB=var.UB=round(current["x"][key])
        released_alloc=0
        for key,var in v["alloc_boxes"].items():
            if (key[0],key[1]) not in pairs:
                value=round(current["alloc_boxes"][key]) if alloc_domain=="integer" else current["alloc_boxes"][key]
                if alloc_domain=="integer" and abs(value-current["alloc_boxes"][key])>1e-5:raise AssertionError("unsafe integer allocation fixing")
                var.LB=var.UB=value
            else:released_alloc+=1
        m.Params.OutputFlag=0;m.Params.TimeLimit=min(repair_time,max(.01,time_limit-(time.perf_counter()-beg)));m.Params.MIPGap=repair_gap;m.Params.Seed=seed+iteration;t=time.perf_counter();m.optimize();runtime=time.perf_counter()-t;accepted=False;candidate=None
        if m.SolCount:
            candidate=extract_solution(v);evaluation=evaluate_solution(data,weights,candidate,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)
            if abs(m.ObjVal-evaluation["core_cost"])>1e-5:raise AssertionError("ALNS repair objective mismatch")
            delta=evaluation["core_cost"]-current_cost;temp=max(1e-9,.02*best_cost*(.98**iteration));accepted=delta<-1e-6 or rng.random()<math.exp(-max(0,delta)/temp)
            if accepted:current,current_cost=candidate,evaluation["core_cost"]
            if evaluation["core_cost"]<best_cost-1e-6:best,best_cost=candidate,evaluation["core_cost"];stats[op]["improved"]+=1;stats[op]["best_improved"]+=1;stats[op]["score"]+=5;streak=0;fraction=max(min_destroy,fraction*.8)
            else:streak+=1;fraction=min(max_destroy,fraction+(max_destroy-min_destroy)/max(1,stall_iters));stats[op]["score"]+=2 if accepted else 0
        stats[op]["used"]+=1;stats[op]["accepted"]+=int(accepted);stats[op]["runtime"]+=runtime;stats[op]["weight"]=.8*stats[op]["weight"]+.2*max(.1,stats[op]["score"]/max(1,stats[op]["used"]));log.append({"iteration":iteration,"operator":op,"destroy_fraction":used_fraction,"released_x_count":len(released),"released_alloc_count":released_alloc,"candidate_ub":None if candidate is None else evaluate_solution(data,weights,candidate,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled)["core_cost"],"best_ub":best_cost,"accepted":accepted,"repair_runtime":runtime})
        if streak>=stall_iters and restart_count<restarts:current=best;current_cost=best_cost;streak=0;restart_count+=1;fraction=max_destroy
    return {"start_ub":start_eval["core_cost"],"best_ub":best_cost,"improvement":start_eval["core_cost"]-best_cost,"best_solution":best,"iterations":log,"operator_stats":stats,"restarts":restart_count,"persistent_repair_model":True,"runtime":time.perf_counter()-beg}

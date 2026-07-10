"""Monolithic ALNS repair and epsilon-constrained attribute refinement for Route B."""
from __future__ import annotations
import math,random,time
import gurobipy as gp
from gurobipy import GRB
from model_common import group_attr,groups,outbound_pressure,remaining_capacity
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution

OPERATORS=("random","active","block","interval","ship","conflict","distance")
def _start(vars,solution):
    for name in ("x","alloc_boxes","din","inv","in_share"):
        for k,value in solution.get(name,{}).items():
            if name in vars and k in vars[name]:vars[name][k].Start=value
def adaptive_lns(data,weights,start_solution,*,time_limit=10,repair_time=2,repair_gap=.03,min_destroy=.1,max_destroy=.35,restarts=1,stall_iters=10,alloc_domain="integer",add_valid_inequalities=True,seed=0):
    rng=random.Random(seed);start_eval=evaluate_solution(data,weights,start_solution);current=start_solution;current_cost=start_eval["core_cost"];best=current;best_cost=current_cost;beg=time.perf_counter();log=[];stats={op:{"used":0,"accepted":0,"improved":0,"best_improved":0,"score":0.0,"weight":1.0,"runtime":0.0} for op in OPERATORS};keys=list(current["x"]);iteration=0;fraction=min_destroy;streak=0;restart_count=0;m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities);pressure=outbound_pressure(data)
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
            candidate=extract_solution(v);evaluation=evaluate_solution(data,weights,candidate)
            if abs(m.ObjVal-evaluation["core_cost"])>1e-5:raise AssertionError("ALNS repair objective mismatch")
            delta=evaluation["core_cost"]-current_cost;temp=max(1e-9,.02*best_cost*(.98**iteration));accepted=delta<-1e-6 or rng.random()<math.exp(-max(0,delta)/temp)
            if accepted:current,current_cost=candidate,evaluation["core_cost"]
            if evaluation["core_cost"]<best_cost-1e-6:best,best_cost=candidate,evaluation["core_cost"];stats[op]["improved"]+=1;stats[op]["best_improved"]+=1;stats[op]["score"]+=5;streak=0;fraction=max(min_destroy,fraction*.8)
            else:streak+=1;fraction=min(max_destroy,fraction+(max_destroy-min_destroy)/max(1,stall_iters));stats[op]["score"]+=2 if accepted else 0
        stats[op]["used"]+=1;stats[op]["accepted"]+=int(accepted);stats[op]["runtime"]+=runtime;stats[op]["weight"]=.8*stats[op]["weight"]+.2*max(.1,stats[op]["score"]/max(1,stats[op]["used"]));log.append({"iteration":iteration,"operator":op,"destroy_fraction":used_fraction,"released_x_count":len(released),"released_alloc_count":released_alloc,"candidate_ub":None if candidate is None else evaluate_solution(data,weights,candidate)["core_cost"],"best_ub":best_cost,"accepted":accepted,"repair_runtime":runtime})
        if streak>=stall_iters and restart_count<restarts:current=best;current_cost=best_cost;streak=0;restart_count+=1;fraction=max_destroy
    return {"start_ub":start_eval["core_cost"],"best_ub":best_cost,"improvement":start_eval["core_cost"]-best_cost,"best_solution":best,"iterations":log,"operator_stats":stats,"restarts":restart_count,"persistent_repair_model":True,"runtime":time.perf_counter()-beg}

def solve_attribute_refinement(data,weights,core_solution,core_ub,*,epsilon=.01,time_limit=10,mip_gap=.03,alloc_domain="integer",attribute_scope="final",add_valid_inequalities=True,seed=0,threads=1):
    G=groups(data);pods=sorted({group_attr(data,g,"pod") for g in G if group_attr(data,g,"pod")!="ALL"});weights_v=sorted({group_attr(data,g,"weight_class") for g in G if group_attr(data,g,"weight_class")!="ALL"});heights=sorted({group_attr(data,g,"height") for g in G if group_attr(data,g,"height")!="ALL"})
    if not data.get("G") or max(len(pods),len(weights_v),len(heights))<2:return {"status":"NOT_APPLICABLE","accepted":False,"solution":core_solution,"attribute_before":None,"attribute_after":None,"core_degradation_absolute":None,"core_degradation_relative":None}
    m,v,e=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities);periods=[max(data["N"])] if attribute_scope=="final" else data["N"];rem=remaining_capacity(data);alpha=float(data["Alpha"]);pod=m.addVars(data["J_new"],pods,data["K"],periods,vtype=GRB.BINARY,name="pod_use");weight=m.addVars(data["J_new"],weights_v,data["K"],periods,vtype=GRB.BINARY,name="weight_use");hu=m.addVars(data["I_list"],heights,periods,vtype=GRB.BINARY,name="height_use");hm=m.addVars(data["I_list"],periods,lb=0,name="height_mix")
    for j in data["J_new"]:
     for attr,values,bins in (("pod",pods,pod),("weight_class",weights_v,weight)):
      for value in values:
       gs=[g for g in G if group_attr(data,g,attr)==value]
       for n in periods:
        for k in data["K"]:
         cap=sum(rem[i,n]/alpha for i in data["Bays_in_Block"][k]);need=sum(sum(float(data.get("Arrivals_group_interval",{}).get((j,g,nn),0)) for nn in data["N"] if nn<=n) for g in gs);m.addConstr(gp.quicksum(v["inv"][j,g,i,n] for i in data["Bays_in_Block"][k] for g in gs)<=min(cap,need)*bins[j,value,k,n])
    for i in data["I_list"]:
     for n in periods:
      for h in heights:m.addConstr(gp.quicksum(v["inv"][j,g,i,n] for j in data["J_new"] for g in G if group_attr(data,g,"height")==h)<=rem[i,n]/alpha*hu[i,h,n])
      m.addConstr(hm[i,n]>=gp.quicksum(hu[i,h,n] for h in heights)-1)
    count=len(periods);scales={"pod":max(1,len(data["J_new"])*len(data["K"])*max(1,len(pods))*count),"weight":max(1,len(data["J_new"])*len(data["K"])*max(1,len(weights_v))*count),"height":max(1,len(data["I_list"])*max(1,len(heights)-1)*count)};attr=weights.objective_scale*(weights.attribute.pod_spread*gp.quicksum(pod.values())/scales["pod"]+weights.attribute.weight_spread*gp.quicksum(weight.values())/scales["weight"]+weights.attribute.height_mix*gp.quicksum(hm.values())/scales["height"]);m.addConstr(e["core_objective"]<=core_ub*(1+epsilon)+1e-6);m.setObjective(attr);_start(v,core_solution);m.Params.OutputFlag=0;m.Params.TimeLimit=time_limit;m.Params.MIPGap=mip_gap;m.Params.Seed=seed;m.Params.Threads=threads;m.optimize();candidate=extract_solution(v) if m.SolCount else None;candidate_core=evaluate_solution(data,weights,candidate)["core_cost"] if candidate else None
    def score(sol):
        if sol is None:return None
        return weights.objective_scale*(weights.attribute.pod_spread*sum(any(sol["inv"][j,g,i,n]>1e-6 for i in data["Bays_in_Block"][k] for g in G if group_attr(data,g,"pod")==p) for j in data["J_new"] for p in pods for k in data["K"] for n in periods)/scales["pod"]+weights.attribute.weight_spread*sum(any(sol["inv"][j,g,i,n]>1e-6 for i in data["Bays_in_Block"][k] for g in G if group_attr(data,g,"weight_class")==w) for j in data["J_new"] for w in weights_v for k in data["K"] for n in periods)/scales["weight"]+weights.attribute.height_mix*sum(max(0,len({group_attr(data,g,"height") for j in data["J_new"] for g in G if sol["inv"][j,g,i,n]>1e-6})-1) for i in data["I_list"] for n in periods)/scales["height"])
    before=score(core_solution);after=score(candidate);error=None if candidate is None else abs(m.ObjVal-after)
    if error is not None and error>1e-5:raise AssertionError("attribute objective mismatch")
    accepted=candidate is not None and candidate_core<=core_ub*(1+epsilon)+1e-5 and after<before-1e-6;absolute=None if candidate_core is None else candidate_core-core_ub;return {"status":"ACCEPTED" if accepted else "REJECTED","accepted":accepted,"candidate_core_cost":candidate_core,"core_degradation_absolute":absolute,"core_degradation_relative":None if absolute is None else absolute/max(abs(core_ub),1e-9),"attribute_before":before,"attribute_after":after,"attribute_objective_error":error,"attribute_scope":attribute_scope,"attribute_basis":"inventory","epsilon":epsilon,"solution":candidate if accepted else core_solution,"status_name":None if not m.SolCount else "OPTIMAL" if m.Status==GRB.OPTIMAL else "TIME_LIMIT"}

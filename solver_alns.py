"""Adaptive trajectory-level monolithic large-neighborhood search."""
from __future__ import annotations
import math,random,time
from gurobipy import GRB
from model_common import group_size,groups,outbound_pressure,remaining_capacity,required_reserve
from model_concentration import evaluate_joint_group_concentration
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution

OPERATORS=("random","active","block","interval","ship","conflict","distance","concentration")
RANKED_OPERATORS={"conflict","distance","concentration"}
def all_pair_keys(data):return [(i,j) for i in data["I_list"] for j in data["J_new"]]
def active_pair_keys(data,solution,tolerance=.5):return sorted((i,j) for i,j in all_pair_keys(data) if any(solution.get("x",{}).get((i,j,n),0)>tolerance for n in data["N"]))
def _period_pair_mass(data,solution,pair,periods):
    i,j=pair;G=groups(data);return sum(float(solution.get("x",{}).get((i,j,n),0))+sum(float(solution.get("alloc_boxes",{}).get((i,j,g,n),0))+float(solution.get("din",{}).get((j,g,i,n),0)) for g in G) for n in periods)
def concentration_destroy_pairs(data,solution,*,alloc_domain="integer"):
    c=evaluate_joint_group_concentration(data,solution,alloc_domain=alloc_domain,enabled=True)
    if not c["enabled"] or not c["positive_ship_groups"]:return [],{}
    target=max(c["positive_ship_groups"],key=lambda p:len(c["used_bays"].get(p,[])));j,g=target;pairs=[(i,j) for i in c["used_bays"].get(target,[])];final=c["final_period"]
    pairs.sort(key=lambda q:float(solution.get("alloc_boxes",{}).get((q[0],j,g,final),0)))
    return pairs,{"target_ship":j,"target_group":g,"target_size":group_size(data,g)}
def concentration_destroy_pool(data,solution,*,alloc_domain="integer"):
    pairs,_=concentration_destroy_pairs(data,solution,alloc_domain=alloc_domain);return pairs
def build_source_pair_pool(data,solution,operator,rng,pressure,alloc_domain="integer"):
    pairs=all_pair_keys(data);active=set(active_pair_keys(data,solution));context={};ranked=operator in RANKED_OPERATORS
    if operator=="active":pool=sorted(active)
    elif operator=="block":
        block=rng.choice(data["K"]);context["block"]=block;eligible=[q for q in pairs if q[0] in data["Bays_in_Block"][block]];preferred=[q for q in eligible if q in active];fallback=[q for q in eligible if q not in active];pool=preferred+fallback;context.update({"preferred_pool":preferred,"fallback_pool":fallback})
    elif operator=="interval":
        start_pos=rng.randrange(len(data["N"]));periods=data["N"][start_pos:];context.update({"free_periods":set(periods),"free_period_start":periods[0]});pool=[q for q in pairs if _period_pair_mass(data,solution,q,periods)>1e-9]
    elif operator=="ship":
        ship=rng.choice(data["J_new"]);context["target_ship"]=ship;eligible=[q for q in pairs if q[1]==ship];preferred=[q for q in eligible if q in active];fallback=[q for q in eligible if q not in active];pool=preferred+fallback;context.update({"preferred_pool":preferred,"fallback_pool":fallback})
    elif operator in {"conflict","distance"}:
        def contribution(q):
            i,j=q;block=data["I"][i]["block"]
            if solution.get("din") is not None:
                flows={n:sum(float(solution["din"].get((j,g,i,n),0)) for g in groups(data)) for n in data["N"]}
            else:flows={n:sum(float(solution.get("alloc_boxes",{}).get((i,j,g,n),0)) for g in groups(data)) for n in data["N"]}
            return sum((pressure[block,n] if operator=="conflict" else float(data["Dist"][j,block]))*flows[n] for n in data["N"])
        pool=sorted([q for q in pairs if contribution(q)>1e-12],key=contribution,reverse=True)
    elif operator=="concentration":pool,context=concentration_destroy_pairs(data,solution,alloc_domain=alloc_domain)
    else:pool=pairs
    return (pool or pairs),{**context,"ranked":ranked}
def select_source_pairs(source_pool,destroy_fraction,rng,ranked=False,preferred_pool=None,fallback_pool=None):
    if not source_pool:return []
    count=min(len(source_pool),max(1,math.ceil(len(source_pool)*destroy_fraction)))
    if ranked:return list(source_pool[:count])
    if preferred_pool is not None:
        preferred=list(preferred_pool);fallback=list(fallback_pool or []);take=min(count,len(preferred));return rng.sample(preferred,take)+rng.sample(fallback,min(count-take,len(fallback)))
    return list(rng.sample(list(source_pool),count))
def select_destination_pairs(data,solution,source_pairs,operator,count,rng,context):
    if count<=0:return []
    source=set(source_pairs);rem=remaining_capacity(data);periods=sorted(context.get("free_periods",data["N"]));final=max(data["N"]);G=groups(data);target_ship=context.get("target_ship");target_group=context.get("target_group");candidates=[]
    maxdist=max([float(x) for x in data["Dist"].values()]+[1]);pressure=outbound_pressure(data);maxpressure=max(list(pressure.values())+[1]);maxcap=max(list(rem.values())+[1]);active=set(active_pair_keys(data,solution))
    for i,j in all_pair_keys(data):
        suffix_capacity=min(rem[i,n] for n in periods)
        if (i,j) in source or (target_ship is not None and operator in {"ship","concentration"} and j!=target_ship) or suffix_capacity<=1e-9:continue
        compatible=[g for g in G if group_size(data,g)==int(data["Fixed_Bay_Mode"][i]) and required_reserve(data,j,g,final,"continuous")>1e-9]
        if target_group is not None:compatible=[g for g in compatible if g==target_group]
        if not compatible:continue
        block=data["I"][i]["block"];dw=2.0 if operator=="distance" else 1.0;pw=2.0 if operator=="conflict" else 1.0;cw=.5 if operator=="concentration" else .25;score=dw*float(data["Dist"][j,block])/maxdist+pw*sum(pressure[block,n] for n in periods)/(len(periods)*maxpressure)-cw*suffix_capacity/maxcap+.10*((i,j) in active)+rng.random()*1e-10;candidates.append((score,(i,j)))
    candidates.sort(key=lambda z:z[0]);return [q for _,q in candidates[:min(count,len(candidates))]]
def build_released_variable_keys(data,released_pairs,free_periods):
    pairs=set(released_pairs);periods=set(free_periods);rx={(i,j,n) for i,j in pairs for n in data["N"] if n in periods};ra={(i,j,g,n) for i,j in pairs for g in groups(data) for n in data["N"] if n in periods};return rx,ra
def _start(vars,solution):
    for name in ("x","alloc_boxes","din","inv","in_share","concentration_use"):
        for k,value in solution.get(name,{}).items():
            if name in vars and k in vars[name]:vars[name][k].Start=value
def adaptive_lns(data,weights,start_solution,*,time_limit=10,repair_time=2,repair_gap=.03,min_destroy=.1,max_destroy=.35,restarts=1,stall_iters=10,destination_ratio=1.0,min_repair_time=None,max_repair_time=None,alloc_domain="integer",add_valid_inequalities=True,concentration_enabled=True,seed=0):
    if time_limit<0 or repair_time<=0 or repair_gap<0 or not 0<=min_destroy<=max_destroy<=1 or destination_ratio<0 or restarts<0 or stall_iters<1:raise ValueError("invalid ALNS parameter range")
    rng=random.Random(seed);start_eval=evaluate_solution(data,weights,start_solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);current=start_solution;current_cost=start_eval["core_cost"];best=current;best_cost=current_cost;beg=time.perf_counter();log=[];stats={op:{"used":0,"accepted":0,"improved":0,"best_improved":0,"candidate_found":0,"total_released_pairs":0,"total_released_x":0,"total_released_alloc":0,"score":0.0,"weight":1.0,"runtime":0.0} for op in OPERATORS};iteration=0;fraction=min_destroy;streak=0;restart_count=0;m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled);pressure=outbound_pressure(data);min_rt=max(.5,.5*repair_time) if min_repair_time is None else min_repair_time;max_rt=max(min_rt,3*repair_time) if max_repair_time is None else max_repair_time
    if min_rt<=0 or max_rt<min_rt:raise ValueError("invalid ALNS repair time bounds")
    deadline=beg+time_limit;terminated_by_deadline=False
    while time.perf_counter()<deadline:
        iteration+=1;op=rng.choices(OPERATORS,weights=[stats[o]["weight"] for o in OPERATORS])[0];used_fraction=fraction;source_pool,context=build_source_pair_pool(data,current,op,rng,pressure,alloc_domain);source=select_source_pairs(source_pool,fraction,rng,context.get("ranked",False),context.get("preferred_pool"),context.get("fallback_pool"));dest_count=math.ceil(len(source)*max(0,destination_ratio));destination=select_destination_pairs(data,current,source,op,dest_count,rng,context);released_pairs=set(source)|set(destination);free_periods=context.get("free_periods",set(data["N"]));released_x,released_alloc=build_released_variable_keys(data,released_pairs,free_periods)
        for var in v["x"].values():var.LB=0;var.UB=1
        for var in v["alloc_boxes"].values():var.LB=0;var.UB=GRB.INFINITY
        _start(v,current)
        for key,var in v["x"].items():
            if key not in released_x:var.LB=var.UB=round(current["x"][key])
        for key,var in v["alloc_boxes"].items():
            if key not in released_alloc:
                value=round(current["alloc_boxes"][key]) if alloc_domain=="integer" else current["alloc_boxes"][key]
                if alloc_domain=="integer" and abs(value-current["alloc_boxes"][key])>1e-5:raise AssertionError("unsafe integer allocation fixing")
                var.LB=var.UB=value
        xratio=len(released_x)/max(1,len(v["x"]));aratio=len(released_alloc)/max(1,len(v["alloc_boxes"]));ratio=.5*(xratio+aratio);adaptive=min(max_rt,max(min_rt,repair_time*(.5+2.5*math.sqrt(max(0,ratio)))));remaining=deadline-time.perf_counter()
        if remaining<=0:terminated_by_deadline=True;break
        repair_limit=min(adaptive,remaining);m.Params.OutputFlag=0;m.Params.TimeLimit=repair_limit;m.Params.MIPGap=repair_gap;m.Params.Seed=seed+iteration;t=time.perf_counter();m.optimize();runtime=time.perf_counter()-t;accepted=False;candidate=None;evaluation=None;candidate_cost=None;improved_current=False;improved_best=False;previous_current_cost=current_cost;previous_best_cost=best_cost
        if m.SolCount:
            candidate=extract_solution(v);evaluation=evaluate_solution(data,weights,candidate,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);candidate_cost=evaluation["core_cost"]
            if abs(m.ObjVal-candidate_cost)>1e-5:raise AssertionError("ALNS repair objective mismatch")
            delta=candidate_cost-previous_current_cost;temp=max(1e-9,.02*best_cost*(.98**iteration));accepted=delta<-1e-6 or rng.random()<math.exp(-max(0,delta)/temp);improved_current=candidate_cost<previous_current_cost-1e-6;improved_best=candidate_cost<previous_best_cost-1e-6
            if improved_current:stats[op]["improved"]+=1
            if accepted:current,current_cost=candidate,candidate_cost
            if improved_best:best,best_cost=candidate,candidate_cost;stats[op]["best_improved"]+=1;stats[op]["score"]+=5;streak=0;fraction=max(min_destroy,fraction*.8)
            else:streak+=1;fraction=min(max_destroy,fraction+(max_destroy-min_destroy)/max(1,stall_iters));stats[op]["score"]+=2 if accepted else 0
        if not m.SolCount:streak+=1;fraction=min(max_destroy,fraction+(max_destroy-min_destroy)/max(1,stall_iters))
        stats[op]["used"]+=1;stats[op]["candidate_found"]+=int(candidate is not None);stats[op]["accepted"]+=int(accepted);stats[op]["runtime"]+=runtime;stats[op]["total_released_pairs"]+=len(released_pairs);stats[op]["total_released_x"]+=len(released_x);stats[op]["total_released_alloc"]+=len(released_alloc);stats[op]["weight"]=.8*stats[op]["weight"]+.2*max(.1,stats[op]["score"]/max(1,stats[op]["used"]));log.append({"iteration":iteration,"operator":op,"destroy_fraction":used_fraction,"source_pool_size":len(source_pool),"source_pair_count":len(source),"destination_pair_count":len(destination),"released_pair_count":len(released_pairs),"released_x_count":len(released_x),"released_alloc_count":len(released_alloc),"free_period_start":context.get("free_period_start",data["N"][0]),"free_period_count":len(free_periods),"neighborhood_ratio":ratio,"adaptive_repair_time_limit":repair_limit,"candidate_found":candidate is not None,"candidate_ub":candidate_cost,"current_ub":current_cost,"best_ub":best_cost,"accepted":accepted,"improved_current":improved_current,"improved_best":improved_best,"repair_runtime":runtime})
        if streak>=stall_iters and restart_count<restarts:current=best;current_cost=best_cost;streak=0;restart_count+=1;fraction=max_destroy
    terminated_by_deadline=terminated_by_deadline or time.perf_counter()>=deadline;return {"start_ub":start_eval["core_cost"],"best_ub":best_cost,"improvement":start_eval["core_cost"]-best_cost,"best_solution":best,"iterations":log,"operator_stats":stats,"restarts":restart_count,"persistent_repair_model":True,"terminated_by_deadline":terminated_by_deadline,"runtime":time.perf_counter()-beg}

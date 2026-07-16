"""Sequential single-cut Classical Benders baseline without callbacks or strengthening."""
from __future__ import annotations
import time
from gurobipy import GRB
from model_common import derive_activation,first_stage_cost
from model_master import build_master_model,extract_master_point
from model_recourse import BendersCutPool,GlobalRecourseOracle
from solution_evaluation import evaluate_common_solution
from anytime import canonicalize

def relative_gap(ub,lb):
    if ub is None or lb is None:return None
    return max(0.0,(ub-lb)/max(abs(ub),1e-9))

def solve_classical_benders(data,weights,*,time_limit,mip_gap=0.0,alloc_domain="integer",concentration_enabled=True,seed=0,threads=1,tolerance=1e-6,max_iterations=None):
    started=time.perf_counter();deadline=started+max(0.0,float(time_limit));pool=BendersCutPool();model,variables,_=build_master_model(data,weights,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);model.Params.OutputFlag=0;model.Params.Threads=int(threads or 1);model.Params.Seed=int(seed);model.Params.MIPGap=float(mip_gap);model.Params.IntFeasTol=1e-9;oracle=GlobalRecourseOracle(data,weights);best_ub=float("inf");best_solution=None;best_evaluation=None;global_lb=None;trace=[];optimality_cuts=feasibility_cuts=cache_hits=0;cache={};first_feasible_time=best_solution_time=None;termination="unknown";iteration=0
    while True:
        if max_iterations is not None and iteration>=max_iterations:termination="iteration_limit";break
        remaining=deadline-time.perf_counter()
        if remaining<=0:termination="time_limit";break
        iteration+=1;model.Params.TimeLimit=remaining;master_started=time.perf_counter();model.optimize();master_runtime=time.perf_counter()-master_started;master_status=int(model.Status);master_name={GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.INF_OR_UNBD:"INF_OR_UNBD"}.get(model.Status,str(model.Status));bound=float(model.ObjBound) if model.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None
        if bound is not None:global_lb=bound if global_lb is None else max(global_lb,bound)
        item={"iteration":iteration,"master_status":master_name,"master_obj":float(model.ObjVal) if model.SolCount else None,"master_bound":bound,"master_runtime":master_runtime,"point_eta":None,"sp_status":None,"sp_value":None,"sp_runtime":0.0,"cut_type":None,"cut_violation":None,"cut_added":False,"ub":None if best_ub==float("inf") else best_ub,"lb":global_lb,"gap":relative_gap(None if best_ub==float("inf") else best_ub,global_lb)}
        if not model.SolCount:
            trace.append(item);termination="master_infeasible" if model.Status in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else "master_no_incumbent";break
        point=extract_master_point(variables);item["point_eta"]=point["eta"];key=tuple(sorted((k,round(v,9)) for k,v in point["alloc_boxes"].items() if abs(v)>1e-9))
        entry=cache.get(key)
        if entry is None:
            sp_started=time.perf_counter();oracle.update_rhs(point["alloc_boxes"]);sp_status=oracle.solve();sp_runtime=time.perf_counter()-sp_started
            if sp_status==GRB.OPTIMAL:entry={"status":sp_status,"q":oracle.objective_value(),"recourse":oracle.solution(),"cut":oracle.build_optimality_cut(point,"classical")}
            elif sp_status==GRB.INFEASIBLE:entry={"status":sp_status,"q":None,"recourse":None,"cut":oracle.build_feasibility_cut(point,"classical")}
            else:trace.append(item);termination=f"recourse_status_{sp_status}";break
            cache[key]=entry
        else:cache_hits+=1;sp_status=entry["status"];sp_runtime=0.0
        item["sp_runtime"]=sp_runtime;item["sp_status"]="OPTIMAL" if sp_status==GRB.OPTIMAL else "INFEASIBLE";item["sp_value"]=entry["q"]
        if sp_status==GRB.INFEASIBLE:
            record=entry["cut"];violation=-record.value_at(point);item["cut_type"]="feasibility";item["cut_violation"]=violation
            if violation<=tolerance:trace.append(item);termination="nonviolated_feasibility_cut";break
            if not pool.add(record):trace.append(item);termination="duplicate_violated_cut";break
            model.addConstr(record.as_expression(variables)>=0,name=f"classical_feas_{feasibility_cuts}");feasibility_cuts+=1;item["cut_added"]=True
        else:
            q=entry["q"];first=first_stage_cost(data,weights,point["alloc_boxes"],alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);exact=first["total"]+q;solution={"x":derive_activation(data,point["alloc_boxes"]),"alloc_boxes":point["alloc_boxes"],**entry["recourse"]}
            if "concentration_use" in point:solution["concentration_use"]=point["concentration_use"]
            evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled,tolerance=tolerance)
            if not evaluation["feasibility"]["feasible"]:raise RuntimeError(f"classical incumbent failed checker: {evaluation['feasibility']}")
            if abs(evaluation["core_cost"]-exact)>tolerance:raise AssertionError("classical objective/evaluator mismatch")
            elapsed=time.perf_counter()-started
            if first_feasible_time is None:first_feasible_time=elapsed
            if exact<best_ub-tolerance:best_ub=exact;best_solution=solution;best_evaluation=evaluation;best_solution_time=elapsed
            record=entry["cut"];violation=q-point["eta"];item["cut_type"]="optimality";item["cut_violation"]=violation
            pending=violation>tolerance
            if pending:
                if not pool.add(record):trace.append(item);termination="duplicate_violated_cut";break
                model.addConstr(record.as_expression(variables)>=0,name=f"classical_opt_{optimality_cuts}");optimality_cuts+=1;item["cut_added"]=True
            gap=relative_gap(best_ub,global_lb);master_bound_valid=model.Status in (GRB.OPTIMAL,GRB.TIME_LIMIT)
            if not pending and master_bound_valid and gap is not None and gap<=mip_gap+tolerance:termination="optimal";item.update({"ub":best_ub,"lb":global_lb,"gap":gap});trace.append(item);break
        item.update({"ub":None if best_ub==float("inf") else best_ub,"lb":global_lb,"gap":relative_gap(None if best_ub==float("inf") else best_ub,global_lb)});trace.append(item);model.update()
    ub=None if best_ub==float("inf") else best_ub;gap=relative_gap(ub,global_lb)
    if ub is not None and global_lb is not None and global_lb>ub+tolerance:raise AssertionError("Classical Benders LB exceeds UB")
    status_name="OPTIMAL" if termination=="optimal" else "TIME_LIMIT" if termination=="time_limit" else "ITERATION_LIMIT" if termination=="iteration_limit" else "STOPPED"
    runtime=time.perf_counter()-started;elapsed=0.0;points=[]
    for item in trace:elapsed+=item["master_runtime"]+item["sp_runtime"];points.append({"time":elapsed,"phase":"main","source":"classical_iteration","ub":item["ub"],"lb":item["lb"]})
    return {"anytime_trace":canonicalize(points,runtime,ub,global_lb),"ok":best_solution is not None,"algorithm":"classical_benders","configuration_status":"baseline","status_name":status_name,"termination_reason":termination,"ub":ub,"lb":global_lb,"gap":gap,"runtime":runtime,"solution":best_solution,"components":best_evaluation,"iterations":iteration,"iteration_trace":trace,"optimality_cuts":optimality_cuts,"feasibility_cuts":feasibility_cuts,"duplicate_cuts":pool.duplicate_skips,"sp_statistics":oracle.statistics(),"cache_hits":cache_hits,"cache_size":len(cache),"first_feasible_time":first_feasible_time,"best_solution_time":best_solution_time,"used_callback":False}

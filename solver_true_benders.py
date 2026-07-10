"""True global Branch-and-Benders-Cut solver with reusable recourse oracle."""
from __future__ import annotations
import time,traceback
import gurobipy as gp
from gurobipy import GRB
from model_common import open_cost
from model_master import build_master_model,extract_master_point
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution
from model_recourse import BendersCutPool,GlobalRecourseOracle

def _status(s):return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.INTERRUPTED:"INTERRUPTED",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def _add_cut(model,vars,record):return model.addConstr(record.as_expression(vars)>=0,name=f"cut_{record.signature[:16]}")
def root_lp_prepass(data,weights,pool,*,alloc_domain="integer",add_valid_inequalities=True,max_iters=20,time_limit=10,tolerance=1e-6):
    started=time.perf_counter();m,v,_=build_master_model(data,weights,alloc_domain=alloc_domain,relax=True,add_valid_inequalities=add_valid_inequalities,cut_pool=pool);oracle=GlobalRecourseOracle(data,weights);initial=final=None;count=0
    for iteration in range(max_iters):
        if time.perf_counter()-started>=time_limit:break
        m.Params.OutputFlag=0;m.Params.TimeLimit=max(.01,time_limit-(time.perf_counter()-started));m.optimize()
        if m.Status not in (GRB.OPTIMAL,GRB.TIME_LIMIT) or m.SolCount==0:break
        if initial is None:initial=float(m.ObjVal)
        final=float(m.ObjVal)
        point=extract_master_point(v);oracle.update_rhs(point["x"],point["alloc_boxes"]);status=oracle.solve()
        if status==GRB.OPTIMAL:
            record=oracle.build_optimality_cut(point,"root");violation=-record.value_at(point)
            if violation<=tolerance:break
        elif status==GRB.INFEASIBLE:record=oracle.build_feasibility_cut(point,"root");violation=-record.value_at(point)
        else:raise RuntimeError(f"root recourse status {status}")
        record.violation=violation
        if pool.add(record):_add_cut(m,v,record);count+=1
        else:break
    if m.SolCount:final=float(m.ObjVal)
    return {"root_initial_bound":initial,"root_final_bound":final,"root_bound_improvement":None if initial is None or final is None else final-initial,"root_cut_count":count,"root_cut_runtime":time.perf_counter()-started,"sp_statistics":oracle.statistics()}

def _warm_start(data,weights,alloc_domain,time_limit,add_valid_inequalities):
    started=time.perf_counter();m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities);m.Params.OutputFlag=0;m.Params.TimeLimit=max(.01,time_limit);m.Params.MIPGap=.10;m.optimize()
    if not m.SolCount:return None
    solution=extract_solution(v);evaluation=evaluate_solution(data,weights,solution);return {"solution":solution,"evaluation":evaluation,"ub":evaluation["core_cost"],"runtime":time.perf_counter()-started}

def solve_bbc_phase(data,weights,*,time_limit,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,node_cuts=True,node_cut_limit=100,seed=0,threads=1,cut_pool=None,start_solution=None,origin_prefix="phase1",warm_start=True):
    pool=cut_pool if cut_pool is not None else BendersCutPool();inherited=len(pool.records);model,vars,_=build_master_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,cut_pool=pool);model.Params.OutputFlag=0;model.Params.TimeLimit=float(time_limit);model.Params.MIPGap=float(mip_gap);model.Params.Seed=int(seed);model.Params.Threads=int(threads or 1);model.Params.LazyConstraints=1;model.Params.PreCrush=1;oracle=GlobalRecourseOracle(data,weights);best={"ub":float("inf"),"point":None,"recourse":None};stats={"initial_optimality_cuts":0,"root_optimality_cuts":0,"incumbent_optimality_cuts":0,"node_optimality_cuts":0,"incumbent_feasibility_cuts":0,"node_feasibility_cuts":0,"max_optimality_violation":0.0,"optimality_violation_sum":0.0,"optimality_checks":0,"max_feasibility_violation":0.0,"farkas_failures":0,"callback_time":0.0,"cache_hits":0,"cache_misses":0};callback_error=[]
    phase_started=time.perf_counter();warm=None
    if start_solution:
        warm={"solution":start_solution,"evaluation":evaluate_solution(data,weights,start_solution),"ub":evaluate_solution(data,weights,start_solution)["core_cost"]}
    elif warm_start:warm=_warm_start(data,weights,alloc_domain,min(5,max(1,time_limit*.15)),add_valid_inequalities)
    warm_runtime=time.perf_counter()-phase_started;model.Params.TimeLimit=max(.01,float(time_limit)-warm_runtime)
    if warm:
        point={"x":warm["solution"]["x"],"alloc_boxes":warm["solution"]["alloc_boxes"],"eta":warm["evaluation"]["recourse_cost"]};oracle.update_rhs(point["x"],point["alloc_boxes"])
        if oracle.solve()==GRB.OPTIMAL:
            record=oracle.build_optimality_cut(point,"initial")
            if pool.add(record):_add_cut(model,vars,record);stats["initial_optimality_cuts"]+=1
            best={"ub":warm["ub"],"point":point,"recourse":{k:warm["solution"][k] for k in ("din","inv","in_share","in_total","avg","g_bal")}}
            for k,val in point["x"].items():vars["x"][k].Start=val
            for k,val in point["alloc_boxes"].items():vars["alloc_boxes"][k].Start=val
            vars["eta"].Start=point["eta"]
    def callback(m,where):
        t=time.perf_counter()
        try:
            if where==GRB.Callback.MIPSOL:
                point=extract_master_point(vars,lambda var:m.cbGetSolution(var));oracle.update_rhs(point["x"],point["alloc_boxes"]);stats["cache_misses"]+=1;status=oracle.solve();origin="incumbent"
                if status==GRB.OPTIMAL:
                    q=oracle.objective_value();record=oracle.build_optimality_cut(point,origin);violation=-record.value_at(point);stats["optimality_checks"]+=1;stats["optimality_violation_sum"]+=max(0,violation);stats["max_optimality_violation"]=max(stats["max_optimality_violation"],violation)
                    if violation>1e-6:
                        if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_optimality_cuts"]+=1
                    exact=open_cost(data,weights,point["x"])+q
                    if exact<best["ub"]-1e-7:best.update({"ub":exact,"point":{**point,"eta":q},"recourse":oracle.solution()})
                elif status==GRB.INFEASIBLE:
                    try:record=oracle.build_feasibility_cut(point,origin)
                    except Exception:
                        stats["farkas_failures"]+=1;oracle.model.write(f"farkas_failure_{origin_prefix}.lp");raise
                    violation=-record.value_at(point);stats["max_feasibility_violation"]=max(stats["max_feasibility_violation"],violation)
                    if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_feasibility_cuts"]+=1
                else:raise RuntimeError(f"recourse status {status}")
            elif where==GRB.Callback.MIPNODE and node_cuts and stats["node_optimality_cuts"]+stats["node_feasibility_cuts"]<node_cut_limit and m.cbGet(GRB.Callback.MIPNODE_STATUS)==GRB.OPTIMAL:
                point=extract_master_point(vars,lambda var:m.cbGetNodeRel(var));oracle.update_rhs(point["x"],point["alloc_boxes"]);stats["cache_misses"]+=1;status=oracle.solve();origin="node"
                if status==GRB.OPTIMAL:
                    record=oracle.build_optimality_cut(point,origin);violation=-record.value_at(point);stats["optimality_checks"]+=1;stats["optimality_violation_sum"]+=max(0,violation);stats["max_optimality_violation"]=max(stats["max_optimality_violation"],violation)
                    if violation>1e-6 and pool.add(record):m.cbCut(record.as_expression(vars)>=0);stats["node_optimality_cuts"]+=1
                elif status==GRB.INFEASIBLE:
                    try:record=oracle.build_feasibility_cut(point,origin)
                    except Exception:
                        stats["farkas_failures"]+=1;oracle.model.write(f"farkas_failure_{origin_prefix}_node.lp");raise
                    violation=-record.value_at(point);stats["max_feasibility_violation"]=max(stats["max_feasibility_violation"],violation)
                    if pool.add(record):m.cbCut(record.as_expression(vars)>=0);stats["node_feasibility_cuts"]+=1
        except Exception as exc:callback_error.append((exc,traceback.format_exc()));m.terminate()
        finally:stats["callback_time"]+=time.perf_counter()-t
    started=time.perf_counter();model.optimize(callback);master_runtime=time.perf_counter()-started;runtime=time.perf_counter()-phase_started
    if callback_error:raise RuntimeError(callback_error[0][1]) from callback_error[0][0]
    lb=float(model.ObjBound) if model.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None;ub=None if best["ub"]==float("inf") else best["ub"]
    if ub is not None and lb is not None and lb>ub+1e-5:raise AssertionError("BBC LB exceeds exact UB")
    full_solution=None
    if best["point"]:
        block_use={(j,k,n):float(any(best["point"]["x"].get((i,j,n),0)>.5 for i in data["Bays_in_Block"][k])) for j in data["J_new"] for k in data["K"] for n in data["N"]};full_solution={"x":best["point"]["x"],"alloc_boxes":best["point"]["alloc_boxes"],"block_use":block_use,**best["recourse"]}
    stats["avg_optimality_violation"]=stats["optimality_violation_sum"]/max(1,stats["optimality_checks"]);stats["duplicate_optimality_cut_skips"]=pool.duplicate_skips
    return {"ok":ub is not None,"status":int(model.Status),"status_name":_status(model.Status),"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"ub_source":"exact_global_recourse_evaluation","lb_source":"benders_master_bound","runtime":runtime,"warm_start_runtime":warm_runtime,"master_runtime":master_runtime,"nodes":float(model.NodeCount),"solution":full_solution,"cut_statistics":stats,"sp_statistics":oracle.statistics(),"cut_pool":pool,"cuts_inherited":inherited,"new_unique_cuts":len(pool.records)-inherited}

def solve_true_benders_pipeline(data,weights,*,phase1_time=20,lns_time=20,phase3_time=20,attribute_time=10,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,root_prepass=True,root_cut_max_iters=20,root_cut_time=10,node_cuts=True,node_cut_limit=100,enable_alns=True,enable_phase3=True,enable_refinement=True,attribute_epsilon=.01,attribute_scope="final",seed=0,threads=1,warm_start=True):
    from solver_alns import adaptive_lns,solve_attribute_refinement
    pool=BendersCutPool();phase0=root_lp_prepass(data,weights,pool,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,max_iters=root_cut_max_iters,time_limit=root_cut_time) if root_prepass else {"disabled":True,"root_cut_count":0};p1=solve_bbc_phase(data,weights,time_limit=phase1_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,node_cuts=node_cuts,node_cut_limit=node_cut_limit,seed=seed,threads=threads,cut_pool=pool,origin_prefix="phase1",warm_start=warm_start)
    if not p1["ok"]:return {"ok":False,"algorithm":"true_bbc_alns","phase0_root_prepass":phase0,"phase1_bbc":p1}
    alns=adaptive_lns(data,weights,p1["solution"],time_limit=lns_time,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,seed=seed) if enable_alns else {"start_ub":p1["ub"],"best_ub":p1["ub"],"improvement":0.0,"best_solution":p1["solution"],"iterations":[],"operator_stats":{},"runtime":0.0,"disabled":True}
    inherited_before=len(pool.records);p3=solve_bbc_phase(data,weights,time_limit=phase3_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,node_cuts=node_cuts,node_cut_limit=node_cut_limit,seed=seed+1,threads=threads,cut_pool=pool,start_solution=alns["best_solution"],origin_prefix="phase3",warm_start=False) if enable_phase3 else {"ok":False,"disabled":True,"lb":None,"runtime":0,"nodes":0}
    candidates=[("phase1",p1["ub"],p1["solution"]),("alns",alns["best_ub"],alns["best_solution"])]+([("phase3",p3["ub"],p3["solution"])] if p3["ok"] else []);source,ub,solution=min(candidates,key=lambda x:x[1]);lbs=[v for v in (p1["lb"],p3.get("lb")) if v is not None];lb=max(lbs) if lbs else None
    if lb is not None and lb>ub+1e-5:raise AssertionError("pipeline LB exceeds UB")
    refinement=solve_attribute_refinement(data,weights,solution,ub,epsilon=attribute_epsilon,time_limit=attribute_time,mip_gap=mip_gap,alloc_domain=alloc_domain,attribute_scope=attribute_scope) if enable_refinement else {"accepted":False,"disabled":True,"solution":solution}
    return {"ok":True,"algorithm":"true_bbc_alns","phase0_root_prepass":phase0,"phase1_bbc":p1,"phase2_alns":alns,"phase3_bbc":p3,"core_best":{"ub":ub,"lb":lb,"gap":None if lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"solution":solution,"solution_source":source,"ub_source":"exact_global_recourse_evaluation","lb_source":"benders_master_bound"},"attribute_refinement":refinement,"cuts_inherited_by_phase3":inherited_before,"new_phase3_cuts":len(pool.records)-inherited_before,"total_unique_cuts":len(pool.records)}

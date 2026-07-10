"""True global Branch-and-Benders-Cut solver with reusable recourse oracle."""
from __future__ import annotations
import time,traceback
import gurobipy as gp
from gurobipy import GRB
from model_common import open_cost
from model_master import build_master_model,extract_master_point
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution
from model_recourse import BendersCutPool,GlobalRecourseOracle
from solution_validation import validate_solution

def _status(s):return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.INTERRUPTED:"INTERRUPTED",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def _add_cut(model,vars,record):return model.addConstr(record.as_expression(vars)>=0,name=f"cut_{record.signature[:16]}")
def root_lp_prepass(data,weights,pool,*,alloc_domain="integer",add_valid_inequalities=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,max_iters=100,time_limit=10,relative_improvement_tol=1e-4,violation_tol=1e-6,stall_iters=5):
    started=time.perf_counter();m,v,ctx=build_master_model(data,weights,alloc_domain=alloc_domain,relax=True,add_valid_inequalities=add_valid_inequalities,cut_pool=pool,aggregate_recourse_lb=aggregate_recourse_lb,analytic_recourse_lb=analytic_recourse_lb);oracle=GlobalRecourseOracle(data,weights);initial=final=None;count=opt_count=feas_count=0;trace=[];stall=0;previous=None
    for iteration in range(max_iters):
        if time.perf_counter()-started>=time_limit:break
        m.Params.OutputFlag=0;m.Params.TimeLimit=max(.01,time_limit-(time.perf_counter()-started));m.optimize()
        if m.Status not in (GRB.OPTIMAL,GRB.TIME_LIMIT) or m.SolCount==0:break
        if initial is None:initial=float(m.ObjVal)
        final=float(m.ObjVal)
        point=extract_master_point(v);sp_before=oracle.total_time;oracle.update_rhs(point["x"],point["alloc_boxes"]);status=oracle.solve();sp_time=oracle.total_time-sp_before;cut_type=None;violation=0
        if status==GRB.OPTIMAL:
            record=oracle.build_optimality_cut(point,"root");violation=-record.value_at(point)
            cut_type="optimality"
            if violation<=violation_tol:
                trace.append({"iteration":iteration,"master_lp_obj":final,"open_component":ctx["open_expression"].getValue(),"eta_component":point["eta"],"sp_status":"OPTIMAL","sp_value":oracle.objective_value(),"cut_type":None,"cut_violation":violation,"bound_improvement":0 if previous is None else final-previous,"sp_time":sp_time});break
        elif status==GRB.INFEASIBLE:record=oracle.build_feasibility_cut(point,"root");violation=-record.value_at(point)
        else:raise RuntimeError(f"root recourse status {status}")
        if status==GRB.INFEASIBLE:cut_type="feasibility"
        improvement=0 if previous is None else final-previous;relative=abs(improvement)/max(1,abs(final));stall=stall+1 if previous is not None and relative<relative_improvement_tol else 0;trace.append({"iteration":iteration,"master_lp_obj":final,"open_component":ctx["open_expression"].getValue(),"eta_component":point["eta"],"sp_status":_status(status),"sp_value":oracle.objective_value() if status==GRB.OPTIMAL else None,"cut_type":cut_type,"cut_violation":violation,"bound_improvement":improvement,"sp_time":sp_time});previous=final;record.violation=violation
        if pool.add(record):_add_cut(m,v,record);count+=1;opt_count+=int(cut_type=="optimality");feas_count+=int(cut_type=="feasibility")
        elif violation>violation_tol:raise RuntimeError("duplicate root cut remains violated; signature/model inconsistency")
        if stall>=stall_iters:break
    if m.SolCount:final=float(m.ObjVal)
    point=extract_master_point(v) if m.SolCount else None;return {"root_initial_bound":initial,"root_final_bound":final,"root_bound_improvement":None if initial is None or final is None else final-initial,"root_cut_count":count,"root_optimality_cuts":opt_count,"root_feasibility_cuts":feas_count,"root_cut_runtime":time.perf_counter()-started,"iteration_trace":trace,"master_open_bound":None if point is None else ctx["open_expression"].getValue(),"master_eta_bound":None if point is None else point["eta"],"aggregate_recourse_bound":None if point is None or ctx["aggregate"]["aggregate_objective"] is None else ctx["aggregate"]["aggregate_objective"].getValue(),"aggregate_distance_bound":None if point is None or ctx["aggregate"].get("distance") is None else ctx["aggregate"]["distance"].getValue(),"aggregate_balance_bound":None if point is None or ctx["aggregate"].get("balance") is None else ctx["aggregate"]["balance"].getValue(),"aggregate_conflict_bound":None if point is None or ctx["aggregate"].get("conflict") is None else ctx["aggregate"]["conflict"].getValue(),"sp_statistics":oracle.statistics()}

def _warm_start(data,weights,alloc_domain,time_limit,add_valid_inequalities):
    started=time.perf_counter();m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities);m.Params.OutputFlag=0;m.Params.TimeLimit=max(.01,time_limit);m.Params.MIPGap=.10;m.optimize()
    if not m.SolCount:return None
    solution=extract_solution(v);report=validate_solution(data,solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities)
    if not report["feasible"]:raise RuntimeError(f"warm solution failed checker: {report}")
    evaluation=evaluate_solution(data,weights,solution);return {"solution":solution,"evaluation":evaluation,"ub":evaluation["core_cost"],"runtime":time.perf_counter()-started}

def solve_bbc_phase(data,weights,*,time_limit,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,cut_strategy="standard",node_cuts=True,node_cut_limit=100,node_separation_policy="root-only",node_separation_interval=20,node_separation_max_depth=10,callback_time_share_limit=.4,seed=0,threads=1,numeric_focus=1,cut_pool=None,start_solution=None,origin_prefix="phase1",warm_start=True):
    pool=cut_pool if cut_pool is not None else BendersCutPool();inherited=len(pool.records);model,vars,ctx=build_master_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,cut_pool=pool,aggregate_recourse_lb=aggregate_recourse_lb,analytic_recourse_lb=analytic_recourse_lb);model.Params.OutputFlag=0;model.Params.TimeLimit=float(time_limit);model.Params.MIPGap=float(mip_gap);model.Params.Seed=int(seed);model.Params.Threads=int(threads or 1);model.Params.NumericFocus=int(numeric_focus);model.Params.LazyConstraints=1;model.Params.PreCrush=1;oracle=GlobalRecourseOracle(data,weights);best={"ub":float("inf"),"point":None,"recourse":None};stats={"initial_optimality_cuts":0,"root_optimality_cuts":0,"incumbent_optimality_cuts":0,"node_optimality_cuts":0,"incumbent_feasibility_cuts":0,"node_feasibility_cuts":0,"max_optimality_violation":0.0,"optimality_violation_sum":0.0,"optimality_checks":0,"max_feasibility_violation":0.0,"farkas_failures":0,"callback_time":0.0,"cache_hits":0,"cache_misses":0,"mipnode_calls":0,"mipnode_sp_solves":0,"mipnode_skips_depth":0,"mipnode_skips_time_budget":0,"mipnode_skips_low_predicted_violation":0,"evaluated_incumbents":0,"exact_incumbents_submitted":0,"exact_incumbents_accepted_by_master":0,"cut_efficacies":[],"cut_coefficient_metrics":[]};callback_error=[]
    phase_started=time.perf_counter();warm=None
    if start_solution:
        warm={"solution":start_solution,"evaluation":evaluate_solution(data,weights,start_solution),"ub":evaluate_solution(data,weights,start_solution)["core_cost"]}
    elif warm_start:warm=_warm_start(data,weights,alloc_domain,min(5,max(1,time_limit*.15)),add_valid_inequalities)
    warm_runtime=time.perf_counter()-phase_started;model.Params.TimeLimit=max(.01,float(time_limit)-warm_runtime)
    core_point=None
    if warm:
        point={"x":warm["solution"]["x"],"alloc_boxes":warm["solution"]["alloc_boxes"],"eta":warm["evaluation"]["recourse_cost"]};oracle.update_rhs(point["x"],point["alloc_boxes"])
        if oracle.solve()==GRB.OPTIMAL:
            record=oracle.build_optimality_cut(point,"initial")
            if pool.add(record):_add_cut(model,vars,record);stats["initial_optimality_cuts"]+=1
            best={"ub":warm["ub"],"point":point,"recourse":{k:warm["solution"][k] for k in ("din","inv","in_share","in_total","avg","g_bal")}}
            for k,val in point["x"].items():vars["x"][k].Start=val
            for k,val in point["alloc_boxes"].items():vars["alloc_boxes"][k].Start=val
            vars["eta"].Start=point["eta"]
            model.Params.Cutoff=warm["ub"]+1e-6
            core_point=point
    solve_started=time.perf_counter()
    def callback(m,where):
        t=time.perf_counter()
        try:
            if where==GRB.Callback.MIPSOL:
                stats["evaluated_incumbents"]+=1;point=extract_master_point(vars,lambda var:m.cbGetSolution(var));oracle.update_rhs(point["x"],point["alloc_boxes"]);stats["cache_misses"]+=1;status=oracle.solve();origin="incumbent"
                if status==GRB.OPTIMAL:
                    q=oracle.objective_value();record=oracle.build_optimality_cut(point,origin);violation=-record.value_at(point);stats["optimality_checks"]+=1;stats["optimality_violation_sum"]+=max(0,violation);stats["max_optimality_violation"]=max(stats["max_optimality_violation"],violation)
                    if violation>1e-6:
                        if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_optimality_cuts"]+=1;stats["cut_efficacies"].append(violation/max(1e-12,sum(v*v for v in [record.eta_coeff,*record.x_coefficients.values(),*record.alloc_coefficients.values()])**.5));stats["cut_coefficient_metrics"].append(record.coefficient_metrics())
                    exact=open_cost(data,weights,point["x"])+q
                    recourse=oracle.solution();candidate={"x":point["x"],"alloc_boxes":point["alloc_boxes"],**recourse};feasibility=validate_solution(data,candidate,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities)
                    if not feasibility["feasible"]:raise RuntimeError(f"exact incumbent failed checker: {feasibility}")
                    if exact<best["ub"]-1e-7:best.update({"ub":exact,"point":{**point,"eta":q},"recourse":recourse})
                    try:
                        for var in vars["x"].values():m.cbSetSolution(var,m.cbGetSolution(var))
                        for var in vars["alloc_boxes"].values():m.cbSetSolution(var,m.cbGetSolution(var))
                        m.cbSetSolution(vars["eta"],q);stats["exact_incumbents_submitted"]+=1
                        if m.cbUseSolution()<GRB.INFINITY:stats["exact_incumbents_accepted_by_master"]+=1
                    except gp.GurobiError as exc:stats["exact_submission_error"]=str(exc)
                elif status==GRB.INFEASIBLE:
                    try:record=oracle.build_feasibility_cut(point,origin)
                    except Exception:
                        stats["farkas_failures"]+=1;oracle.model.write(f"farkas_failure_{origin_prefix}.lp");raise
                    violation=-record.value_at(point);stats["max_feasibility_violation"]=max(stats["max_feasibility_violation"],violation)
                    if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_feasibility_cuts"]+=1
                else:raise RuntimeError(f"recourse status {status}")
            elif where==GRB.Callback.MIPNODE and node_cuts and node_separation_policy!="off" and stats["node_optimality_cuts"]+stats["node_feasibility_cuts"]<node_cut_limit and m.cbGet(GRB.Callback.MIPNODE_STATUS)==GRB.OPTIMAL:
                stats["mipnode_calls"]+=1;node=int(m.cbGet(GRB.Callback.MIPNODE_NODCNT));elapsed=max(1e-9,time.perf_counter()-solve_started)
                if node_separation_policy=="root-only" and node>0:return
                if node_separation_policy=="periodic" and node%max(1,node_separation_interval)!=0:return
                if stats["callback_time"]/elapsed>callback_time_share_limit:stats["mipnode_skips_time_budget"]+=1;return
                point=extract_master_point(vars,lambda var:m.cbGetNodeRel(var));predicted=max([-record.value_at(point) for record in pool.records]+[0])
                if node_separation_policy=="adaptive" and predicted<1e-5:stats["mipnode_skips_low_predicted_violation"]+=1;return
                separation_point=point
                if cut_strategy=="stabilized" and core_point is not None:separation_point={"x":{k:.5*point["x"][k]+.5*core_point["x"][k] for k in point["x"]},"alloc_boxes":{k:.5*point["alloc_boxes"][k]+.5*core_point["alloc_boxes"][k] for k in point["alloc_boxes"]},"eta":point["eta"]}
                stats["mipnode_sp_solves"]+=1;oracle.update_rhs(separation_point["x"],separation_point["alloc_boxes"]);stats["cache_misses"]+=1;status=oracle.solve();origin="node_stabilized" if cut_strategy=="stabilized" else "node"
                if status==GRB.OPTIMAL:
                    record=oracle.build_optimality_cut(separation_point,origin);violation=-record.value_at(point);stats["optimality_checks"]+=1;stats["optimality_violation_sum"]+=max(0,violation);stats["max_optimality_violation"]=max(stats["max_optimality_violation"],violation)
                    if violation>1e-6 and pool.add(record):m.cbCut(record.as_expression(vars)>=0);stats["node_optimality_cuts"]+=1;stats["cut_efficacies"].append(violation/max(1e-12,sum(v*v for v in [record.eta_coeff,*record.x_coefficients.values(),*record.alloc_coefficients.values()])**.5));stats["cut_coefficient_metrics"].append(record.coefficient_metrics())
                elif status==GRB.INFEASIBLE:
                    try:record=oracle.build_feasibility_cut(separation_point,origin)
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
    stats["avg_optimality_violation"]=stats["optimality_violation_sum"]/max(1,stats["optimality_checks"]);stats["duplicate_optimality_cut_skips"]=pool.duplicate_skips;stats["callback_time_share"]=stats["callback_time"]/max(runtime,1e-9)
    point=extract_master_point(vars) if model.SolCount else None;diagnostics={"master_open_bound":None if point is None else ctx["open_expression"].getValue(),"master_eta_bound":None if point is None else point["eta"],"aggregate_recourse_bound":None if point is None or ctx["aggregate"]["aggregate_objective"] is None else ctx["aggregate"]["aggregate_objective"].getValue(),"aggregate_distance_bound":None if point is None or ctx["aggregate"].get("distance") is None else ctx["aggregate"]["distance"].getValue(),"aggregate_balance_bound":None if point is None or ctx["aggregate"].get("balance") is None else ctx["aggregate"]["balance"].getValue(),"aggregate_conflict_bound":None if point is None or ctx["aggregate"].get("conflict") is None else ctx["aggregate"]["conflict"].getValue()}
    return {"ok":ub is not None,"status":int(model.Status),"status_name":_status(model.Status),"ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"ub_source":"exact_global_recourse_evaluation","lb_source":"benders_master_bound","runtime":runtime,"warm_start_runtime":warm_runtime,"master_runtime":master_runtime,"nodes":float(model.NodeCount),"solution":full_solution,"cut_statistics":stats,"sp_statistics":oracle.statistics(),"master_diagnostics":diagnostics,"cut_pool":pool,"cuts_inherited":inherited,"new_unique_cuts":len(pool.records)-inherited}

def solve_true_benders_pipeline(data,weights,*,total_core_time=60,root_time_share=.2,warm_start_time_share=.05,alns_time_share=.15,main_bbc_time_share=.6,phase1_time=20,lns_time=20,phase3_time=20,attribute_time=10,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,aggregate_recourse_lb=True,analytic_recourse_lb=True,cut_strategy="standard",root_prepass=True,root_cut_max_iters=100,root_cut_time=None,root_cut_relative_improvement_tol=1e-4,root_cut_violation_tol=1e-6,root_cut_stall_iters=5,node_cuts=True,node_cut_limit=100,node_separation_policy="root-only",node_separation_interval=20,callback_time_share_limit=.4,enable_alns=True,enable_phase3=True,enable_refinement=True,attribute_epsilon=.01,attribute_scope="final",seed=0,threads=1,warm_start=True,legacy_two_bbc_phases=False,numeric_focus=1,lns_options=None):
    from solver_alns import adaptive_lns,solve_attribute_refinement
    total=float(total_core_time);root_time=float(root_cut_time) if root_cut_time is not None else total*root_time_share;warm_time=total*warm_start_time_share;alns_budget=total*alns_time_share;main_time=total*main_bbc_time_share if root_cut_time is None else max(.01,total-root_time-warm_time-alns_budget)
    if root_time+warm_time+alns_budget+main_time>total+1e-6:raise ValueError("core time shares exceed total budget")
    pool=BendersCutPool();phase0=root_lp_prepass(data,weights,pool,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,aggregate_recourse_lb=aggregate_recourse_lb,analytic_recourse_lb=analytic_recourse_lb,max_iters=root_cut_max_iters,time_limit=root_time,relative_improvement_tol=root_cut_relative_improvement_tol,violation_tol=root_cut_violation_tol,stall_iters=root_cut_stall_iters) if root_prepass else {"disabled":True,"root_cut_count":0,"root_cut_runtime":0};warm=_warm_start(data,weights,alloc_domain,warm_time,add_valid_inequalities) if warm_start else None
    if warm is None:
        p1=solve_bbc_phase(data,weights,time_limit=max(warm_time,1),mip_gap=.15,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,aggregate_recourse_lb=aggregate_recourse_lb,analytic_recourse_lb=analytic_recourse_lb,node_cuts=False,seed=seed,threads=threads,cut_pool=pool,origin_prefix="warm",warm_start=True)
        if p1["ok"]:warm={"solution":p1["solution"],"ub":p1["ub"],"evaluation":evaluate_solution(data,weights,p1["solution"]),"runtime":p1["runtime"]}
    else:p1={"ok":True,"status_name":"WARM_START","ub":warm["ub"],"lb":None,"gap":None,"solution":warm["solution"],"runtime":warm.get("runtime",0),"cut_statistics":{},"sp_statistics":{}}
    options=dict(lns_options or {});alns=adaptive_lns(data,weights,warm["solution"],time_limit=alns_budget,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,seed=seed,**options) if enable_alns and warm is not None else {"start_ub":None if warm is None else warm["ub"],"best_ub":None if warm is None else warm["ub"],"improvement":0.0,"best_solution":None if warm is None else warm["solution"],"iterations":[],"operator_stats":{},"runtime":0.0,"disabled":True,"reason":"no warm incumbent" if warm is None else "disabled"}
    inherited_before=len(pool.records);p3=solve_bbc_phase(data,weights,time_limit=main_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,aggregate_recourse_lb=aggregate_recourse_lb,analytic_recourse_lb=analytic_recourse_lb,cut_strategy=cut_strategy,node_cuts=node_cuts,node_cut_limit=node_cut_limit,node_separation_policy=node_separation_policy,node_separation_interval=node_separation_interval,callback_time_share_limit=callback_time_share_limit,seed=seed+1,threads=threads,numeric_focus=numeric_focus,cut_pool=pool,start_solution=alns["best_solution"],origin_prefix="main",warm_start=False) if enable_phase3 else {"ok":False,"disabled":True,"lb":None,"runtime":0,"nodes":0}
    candidates=[]
    if warm is not None:candidates.append(("warm",warm["ub"],warm["solution"]))
    if alns.get("best_solution") is not None:candidates.append(("alns",alns["best_ub"],alns["best_solution"]))
    if p3["ok"]:candidates.append(("main_bbc",p3["ub"],p3["solution"]))
    if not candidates:return {"ok":False,"algorithm":"true_bbc_alns","workflow":"single_main_bbc","phase0_root_prepass":phase0,"phase1_bbc":p1,"phase2_alns":alns,"phase3_bbc":p3}
    source,ub,solution=min(candidates,key=lambda x:x[1]);lb=p3.get("lb")
    if lb is not None and lb>ub+1e-5:raise AssertionError("pipeline LB exceeds UB")
    refinement=solve_attribute_refinement(data,weights,solution,ub,epsilon=attribute_epsilon,time_limit=attribute_time,mip_gap=mip_gap,alloc_domain=alloc_domain,attribute_scope=attribute_scope,add_valid_inequalities=add_valid_inequalities,seed=seed,threads=threads) if enable_refinement else {"accepted":False,"disabled":True,"solution":solution}
    return {"ok":True,"algorithm":"true_bbc_alns","workflow":"single_main_bbc","time_budget":{"total_core_time":total,"root":root_time,"warm":warm_time,"alns":alns_budget,"main_bbc":main_time},"phase0_root_prepass":phase0,"phase1_bbc":p1,"phase2_alns":alns,"phase3_bbc":p3,"core_best":{"ub":ub,"lb":lb,"gap":None if lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"solution":solution,"solution_source":source,"ub_source":"exact_global_recourse_evaluation","lb_source":"benders_master_bound","feasibility_report":validate_solution(data,solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities)},"attribute_refinement":refinement,"cuts_inherited_by_phase3":inherited_before,"new_phase3_cuts":len(pool.records)-inherited_before,"total_unique_cuts":len(pool.records)}

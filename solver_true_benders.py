"""True global Branch-and-Benders-Cut solver with reusable recourse oracle."""
from __future__ import annotations
import time,traceback
import gurobipy as gp
from gurobipy import GRB
from model_common import first_stage_cost
from model_master import build_master_model,extract_master_point
from model_monolithic import build_monolithic_model,extract_solution
from solution_evaluation import evaluate_common_solution as evaluate_solution
from model_recourse import BendersCutPool,GlobalRecourseOracle
from solution_validation import validate_solution
from anytime import canonicalize

def _status(s):return {GRB.OPTIMAL:"OPTIMAL",GRB.TIME_LIMIT:"TIME_LIMIT",GRB.INFEASIBLE:"INFEASIBLE",GRB.INTERRUPTED:"INTERRUPTED",GRB.SUBOPTIMAL:"SUBOPTIMAL"}.get(s,str(s))
def _add_cut(model,vars,record):return model.addConstr(record.as_expression(vars)>=0,name=f"cut_{record.signature[:16]}")
def remaining_time(deadline):return max(0.0,deadline-time.perf_counter())
def master_point_cache_key(point,alloc_domain):
    if alloc_domain=="integer":
        active=tuple(sorted(k for k,v in point["x"].items() if v>.5));positive=[]
        for k,v in point["alloc_boxes"].items():
            if abs(v)>1e-9:
                if abs(v-round(v))>1e-5:raise AssertionError("noninteger allocation at integer MIPSOL")
                positive.append((k,int(round(v))))
        return ("integer",active,tuple(sorted(positive)))
    xvalues=tuple(sorted((k,float(v).hex()) for k,v in point["x"].items() if abs(v)>1e-15));allocvalues=tuple(sorted((k,float(v).hex()) for k,v in point["alloc_boxes"].items() if abs(v)>1e-15));return ("continuous",xvalues,allocvalues)
def root_lp_prepass(data,weights,pool,*,alloc_domain="integer",add_valid_inequalities=True,valid_inequality_profile="common",aggregate_recourse_lb=True,aggregate_relaxation_level="size",analytic_recourse_lb=True,concentration_enabled=True,max_iters=100,time_limit=10,relative_improvement_tol=1e-4,violation_tol=1e-6,stall_iters=5):
    started=time.perf_counter();m,v,ctx=build_master_model(data,weights,alloc_domain=alloc_domain,relax=True,add_valid_inequalities=add_valid_inequalities,valid_inequality_profile=valid_inequality_profile,cut_pool=pool,aggregate_recourse_lb=aggregate_recourse_lb,aggregate_relaxation_level=aggregate_relaxation_level,analytic_recourse_lb=analytic_recourse_lb,concentration_enabled=concentration_enabled);oracle=GlobalRecourseOracle(data,weights);initial=final=None;count=opt_count=feas_count=0;last_solved_cut_count=0;trace=[];stall=0;previous=None
    for iteration in range(max_iters):
        if time.perf_counter()-started>=time_limit:break
        remaining=time_limit-(time.perf_counter()-started)
        if remaining<=0:break
        m.Params.OutputFlag=0;m.Params.TimeLimit=remaining;m.optimize();last_solved_cut_count=count
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
    resolved=last_solved_cut_count==count;last_solved_bound=final;point=extract_master_point(v) if m.SolCount else None;concentration_bound=None if point is None else (ctx["concentration_expression"].getValue() if hasattr(ctx["concentration_expression"],"getValue") else 0.0);return {"root_initial_bound":initial,"root_final_bound":last_solved_bound if resolved else None,"root_last_solved_bound":last_solved_bound,"root_last_solved_cut_count":last_solved_cut_count,"root_total_cut_count":count,"root_bound_resolved_after_last_cut":resolved,"root_bound_improvement":None if initial is None or not resolved or last_solved_bound is None else last_solved_bound-initial,"root_cut_count":count,"root_optimality_cuts":opt_count,"root_feasibility_cuts":feas_count,"root_cut_runtime":time.perf_counter()-started,"iteration_trace":trace,"master_open_bound":None if point is None else ctx["open_expression"].getValue(),"master_concentration_bound":concentration_bound,"master_eta_bound":None if point is None else point["eta"],"aggregate_recourse_bound":None if point is None or ctx["aggregate"]["aggregate_objective"] is None else ctx["aggregate"]["aggregate_objective"].getValue(),"aggregate_distance_bound":None if point is None or ctx["aggregate"].get("distance") is None else ctx["aggregate"]["distance"].getValue(),"aggregate_balance_bound":None if point is None or ctx["aggregate"].get("balance") is None else ctx["aggregate"]["balance"].getValue(),"aggregate_conflict_bound":None if point is None or ctx["aggregate"].get("conflict") is None else ctx["aggregate"]["conflict"].getValue(),"sp_statistics":oracle.statistics()}

def _warm_start(data,weights,alloc_domain,time_limit,add_valid_inequalities,concentration_enabled=True):
    started=time.perf_counter();deadline=started+max(0,time_limit);m,v,_=build_monolithic_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled);build_runtime=time.perf_counter()-started;remaining=remaining_time(deadline)
    if remaining<=0:return None
    m.Params.OutputFlag=0;m.Params.TimeLimit=remaining;m.Params.MIPGap=.10;m.optimize()
    if not m.SolCount:return None
    solution=extract_solution(v);report=validate_solution(data,solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled)
    if not report["feasible"]:raise RuntimeError(f"warm solution failed checker: {report}")
    evaluation=evaluate_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);return {"solution":solution,"evaluation":evaluation,"ub":evaluation["core_cost"],"model_build_runtime":build_runtime,"optimization_runtime":time.perf_counter()-started-build_runtime,"runtime":time.perf_counter()-started}

def solve_bbc_phase(data,weights,*,time_limit,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,valid_inequality_profile="common",aggregate_recourse_lb=True,aggregate_relaxation_level="size",analytic_recourse_lb=True,concentration_enabled=True,cut_strategy="standard",node_cuts=False,node_cut_limit=100,node_separation_policy="root-only",node_separation_interval=20,callback_time_share_limit=.4,seed=0,threads=1,numeric_focus=1,cut_pool=None,start_solution=None,origin_prefix="phase1",warm_start=True):
    phase_started=time.perf_counter();phase_deadline=phase_started+max(0,float(time_limit))
    anytime=[];last_bound=[None]
    pool=cut_pool if cut_pool is not None else BendersCutPool();inherited=len(pool.records);t=time.perf_counter();model,vars,ctx=build_master_model(data,weights,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,valid_inequality_profile=valid_inequality_profile,cut_pool=pool,aggregate_recourse_lb=aggregate_recourse_lb,aggregate_relaxation_level=aggregate_relaxation_level,analytic_recourse_lb=analytic_recourse_lb,concentration_enabled=concentration_enabled);model_build_runtime=time.perf_counter()-t;model.Params.OutputFlag=0;model.Params.MIPGap=float(mip_gap);model.Params.Seed=int(seed);model.Params.Threads=int(threads or 1);model.Params.NumericFocus=int(numeric_focus);model.Params.LazyConstraints=1;model.Params.PreCrush=1;t=time.perf_counter();oracle=GlobalRecourseOracle(data,weights);oracle_build_runtime=time.perf_counter()-t;best={"ub":float("inf"),"point":None,"recourse":None};stats={"initial_optimality_cuts":0,"root_optimality_cuts":0,"incumbent_optimality_cuts":0,"node_optimality_cuts":0,"incumbent_feasibility_cuts":0,"node_feasibility_cuts":0,"max_optimality_violation":0.0,"optimality_violation_sum":0.0,"optimality_checks":0,"max_feasibility_violation":0.0,"farkas_failures":0,"callback_time":0.0,"cache_hits":0,"cache_misses":0,"mipnode_calls":0,"mipnode_sp_solves":0,"mipnode_skips_time_budget":0,"mipnode_skips_low_predicted_violation":0,"evaluated_incumbents":0,"exact_incumbents_submitted":0,"exact_incumbents_accepted_by_master":None,"submitted_concentration_cost":[],"cut_efficacies":[],"cut_coefficient_metrics":[]};callback_error=[];stats["cache_seeded_entries"]=0;stats["exact_solutions_queued"]=0;stats["exact_solution_acceptance_observable_in_mipsol"]=False;recourse_cache={};warm=None
    if start_solution:
        evaluation=evaluate_solution(data,weights,start_solution,alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);warm={"solution":start_solution,"evaluation":evaluation,"ub":evaluation["core_cost"]}
    elif warm_start:warm=_warm_start(data,weights,alloc_domain,min(5,max(1,time_limit*.15)),add_valid_inequalities,concentration_enabled)
    warm_runtime=max(0,time.perf_counter()-phase_started-model_build_runtime-oracle_build_runtime);phase_remaining=remaining_time(phase_deadline);model.Params.TimeLimit=phase_remaining
    core_point=None
    if warm:
        point={"x":warm["solution"]["x"],"alloc_boxes":warm["solution"]["alloc_boxes"],"eta":warm["evaluation"]["recourse_cost"]};oracle.update_rhs(point["x"],point["alloc_boxes"])
        status=oracle.solve()
        if status!=GRB.OPTIMAL:raise RuntimeError("The supplied start solution is monolithic-feasible but its global recourse is not optimal/feasible.")
        if abs(oracle.objective_value()-warm["evaluation"]["recourse_cost"])>1e-5:raise RuntimeError("initial recourse objective consistency error")
        if status==GRB.OPTIMAL:
            record=oracle.build_optimality_cut(point,"initial");recourse_cache[master_point_cache_key(point,alloc_domain)]={"status":status,"q":oracle.objective_value(),"record":record,"recourse":oracle.solution()};stats["cache_seeded_entries"]=1
            if pool.add(record):_add_cut(model,vars,record);stats["initial_optimality_cuts"]+=1
            best={"ub":warm["ub"],"point":point,"recourse":{k:warm["solution"][k] for k in ("din","inv","in_share","in_total","avg","g_bal")}}
            anytime.append({"time":time.perf_counter()-phase_started,"phase":"warm","source":"warm_incumbent","ub":warm["ub"],"lb":None})
            for k,val in point["x"].items():vars["x"][k].Start=val
            for k,val in point["alloc_boxes"].items():vars["alloc_boxes"][k].Start=val
            for (j,g,i),var in vars.get("concentration_use",{}).items():var.Start=float(point["alloc_boxes"].get((i,j,g,max(data["N"])),0)>1e-6)
            vars["eta"].Start=point["eta"]
            model.Params.Cutoff=warm["ub"]+1e-6
            core_point=point
    solve_started=time.perf_counter()
    def callback(m,where):
        t=time.perf_counter()
        try:
            if where==GRB.Callback.MIPSOL:
                stats["evaluated_incumbents"]+=1;point=extract_master_point(vars,lambda var:m.cbGetSolution(var));origin="incumbent";key=master_point_cache_key(point,alloc_domain);entry=recourse_cache.get(key)
                if entry is None:
                    stats["cache_misses"]+=1;oracle.update_rhs(point["x"],point["alloc_boxes"]);status=oracle.solve()
                    if status==GRB.OPTIMAL:entry={"status":status,"q":oracle.objective_value(),"record":oracle.build_optimality_cut(point,origin),"recourse":oracle.solution()}
                    elif status==GRB.INFEASIBLE:entry={"status":status,"q":None,"record":oracle.build_feasibility_cut(point,origin),"recourse":None}
                    else:raise RuntimeError(f"recourse status {status}")
                    recourse_cache[key]=entry
                else:stats["cache_hits"]+=1;status=entry["status"]
                if status==GRB.OPTIMAL:
                    q=entry["q"];record=entry["record"];violation=-record.value_at(point);stats["optimality_checks"]+=1;stats["optimality_violation_sum"]+=max(0,violation);stats["max_optimality_violation"]=max(stats["max_optimality_violation"],violation)
                    if violation>1e-6:
                        if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_optimality_cuts"]+=1;stats["cut_efficacies"].append(violation/max(1e-12,sum(v*v for v in [record.eta_coeff,*record.x_coefficients.values(),*record.alloc_coefficients.values()])**.5));stats["cut_coefficient_metrics"].append(record.coefficient_metrics())
                    first=first_stage_cost(data,weights,point["x"],point["alloc_boxes"],alloc_domain=alloc_domain,concentration_enabled=concentration_enabled);exact=first["total"]+q
                    recourse=entry["recourse"];candidate={"x":point["x"],"alloc_boxes":point["alloc_boxes"],**recourse};feasibility=validate_solution(data,candidate,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=concentration_enabled)
                    if not feasibility["feasible"]:raise RuntimeError(f"exact incumbent failed checker: {feasibility}")
                    if exact<best["ub"]-1e-7:
                        best.update({"ub":exact,"point":{**point,"eta":q},"recourse":recourse});anytime.append({"time":time.perf_counter()-phase_started,"phase":"main","source":"exact_recourse_mipsol","ub":exact,"lb":None})
                    try:
                        for var in vars["x"].values():m.cbSetSolution(var,m.cbGetSolution(var))
                        for var in vars["alloc_boxes"].values():m.cbSetSolution(var,m.cbGetSolution(var))
                        for (j,g,i),var in vars.get("concentration_use",{}).items():m.cbSetSolution(var,float(point["alloc_boxes"].get((i,j,g,max(data["N"])),0)>1e-6))
                        m.cbSetSolution(vars["eta"],q);stats["exact_incumbents_submitted"]+=1
                        stats["submitted_concentration_cost"].append(first["concentration_cost"])
                        m.cbUseSolution();stats["exact_solutions_queued"]+=1
                    except gp.GurobiError as exc:stats["exact_submission_error"]=str(exc)
                elif status==GRB.INFEASIBLE:
                    try:record=entry["record"]
                    except Exception:
                        stats["farkas_failures"]+=1;oracle.model.write(f"farkas_failure_{origin_prefix}.lp");raise
                    violation=-record.value_at(point);stats["max_feasibility_violation"]=max(stats["max_feasibility_violation"],violation)
                    if pool.add(record):m.cbLazy(record.as_expression(vars)>=0);stats["incumbent_feasibility_cuts"]+=1
                else:raise RuntimeError(f"recourse status {status}")
            elif where==GRB.Callback.MIP:
                bound=float(m.cbGet(GRB.Callback.MIP_OBJBND));threshold=max(1e-6,.001*max(1,abs(last_bound[0] or 0)))
                if last_bound[0] is None or bound>last_bound[0]+threshold:last_bound[0]=bound;anytime.append({"time":time.perf_counter()-phase_started,"phase":"main","source":"master_bound","ub":None,"lb":bound})
            elif where==GRB.Callback.MIPNODE and node_cuts and stats["node_optimality_cuts"]+stats["node_feasibility_cuts"]<node_cut_limit and m.cbGet(GRB.Callback.MIPNODE_STATUS)==GRB.OPTIMAL:
                stats["mipnode_calls"]+=1;node=int(m.cbGet(GRB.Callback.MIPNODE_NODCNT));elapsed=max(1e-9,time.perf_counter()-solve_started)
                if node_separation_policy=="root-only" and node>0:return
                if node_separation_policy=="periodic" and node%max(1,node_separation_interval)!=0:return
                if stats["callback_time"]/elapsed>callback_time_share_limit:stats["mipnode_skips_time_budget"]+=1;return
                point=extract_master_point(vars,lambda var:m.cbGetNodeRel(var));predicted=max([-record.value_at(point) for record in pool.records]+[0])
                if node_separation_policy=="adaptive" and predicted<1e-5:stats["mipnode_skips_low_predicted_violation"]+=1;return
                separation_point=point
                if cut_strategy=="stabilized" and core_point is not None:separation_point={"x":{k:.5*point["x"][k]+.5*core_point["x"][k] for k in point["x"]},"alloc_boxes":{k:.5*point["alloc_boxes"][k]+.5*core_point["alloc_boxes"][k] for k in point["alloc_boxes"]},"eta":point["eta"]}
                stats["mipnode_sp_solves"]+=1;oracle.update_rhs(separation_point["x"],separation_point["alloc_boxes"]);status=oracle.solve();origin="node_stabilized" if cut_strategy=="stabilized" else "node"
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
    phase_remaining=remaining_time(phase_deadline);model.Params.TimeLimit=phase_remaining;started=time.perf_counter()
    if phase_remaining>0:model.optimize(callback)
    master_runtime=time.perf_counter()-started;runtime=time.perf_counter()-phase_started
    if callback_error:raise RuntimeError(callback_error[0][1]) from callback_error[0][0]
    lb=float(model.ObjBound) if phase_remaining>0 and model.Status not in (GRB.INFEASIBLE,GRB.INF_OR_UNBD) else None;ub=None if best["ub"]==float("inf") else best["ub"]
    if ub is not None and lb is not None and lb>ub+1e-5:raise AssertionError("BBC LB exceeds exact UB")
    full_solution=None
    if best["point"]:
        block_use={(j,k,n):float(any(best["point"]["x"].get((i,j,n),0)>.5 for i in data["Bays_in_Block"][k])) for j in data["J_new"] for k in data["K"] for n in data["N"]};full_solution={"x":best["point"]["x"],"alloc_boxes":best["point"]["alloc_boxes"],"block_use":block_use,**best["recourse"]}
        if "concentration_use" in best["point"]:full_solution["concentration_use"]=best["point"]["concentration_use"]
    stats["avg_optimality_violation"]=stats["optimality_violation_sum"]/max(1,stats["optimality_checks"]);stats["duplicate_optimality_cut_skips"]=pool.duplicate_skips;stats["callback_time_share"]=stats["callback_time"]/max(runtime,1e-9);stats["cache_size"]=len(recourse_cache);stats["cache_hit_rate"]=stats["cache_hits"]/max(1,stats["cache_hits"]+stats["cache_misses"])
    point=extract_master_point(vars) if model.SolCount else None;diagnostics={"master_open_bound":None if point is None else ctx["open_expression"].getValue(),"master_concentration_bound":None if point is None else (ctx["concentration_expression"].getValue() if hasattr(ctx["concentration_expression"],"getValue") else 0.0),"master_eta_bound":None if point is None else point["eta"],"aggregate_recourse_bound":None if point is None or ctx["aggregate"]["aggregate_objective"] is None else ctx["aggregate"]["aggregate_objective"].getValue(),"aggregate_distance_bound":None if point is None or ctx["aggregate"].get("distance") is None else ctx["aggregate"]["distance"].getValue(),"aggregate_balance_bound":None if point is None or ctx["aggregate"].get("balance") is None else ctx["aggregate"]["balance"].getValue(),"aggregate_conflict_bound":None if point is None or ctx["aggregate"].get("conflict") is None else ctx["aggregate"]["conflict"].getValue(),"master_strengthening":ctx["master_strengthening"]}
    return {"anytime_trace":canonicalize(anytime,runtime,ub,lb),"ok":ub is not None,"status":int(model.Status) if phase_remaining>0 else None,"status_name":_status(model.Status) if phase_remaining>0 else "DEADLINE_EXHAUSTED","ub":ub,"lb":lb,"gap":None if ub is None or lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"ub_source":"exact_global_recourse_evaluation","lb_source":"benders_master_bound","model_build_runtime":model_build_runtime,"oracle_build_runtime":oracle_build_runtime,"optimization_runtime":master_runtime,"runtime":runtime,"warm_start_runtime":warm_runtime,"master_runtime":master_runtime,"nodes":float(model.NodeCount) if phase_remaining>0 else 0.0,"solution":full_solution,"cut_statistics":stats,"sp_statistics":oracle.statistics(),"master_diagnostics":diagnostics,"cut_pool":pool,"cuts_inherited":inherited,"new_unique_cuts":len(pool.records)-inherited}

def solve_true_benders_pipeline(data,weights,*,total_core_time=60,root_time_share=.05,warm_start_time_share=.15,alns_time_share=.25,main_bbc_time_share=.55,mip_gap=.03,alloc_domain="integer",add_valid_inequalities=True,valid_inequality_profile="common",aggregate_recourse_lb=True,aggregate_relaxation_level="size",analytic_recourse_lb=True,concentration_enabled=True,cut_strategy="standard",root_prepass=True,root_cut_max_iters=100,root_cut_time=None,root_cut_relative_improvement_tol=1e-4,root_cut_violation_tol=1e-6,root_cut_stall_iters=5,node_cuts=False,node_cut_limit=100,node_separation_policy="root-only",node_separation_interval=20,callback_time_share_limit=.4,enable_alns=True,enable_phase3=True,seed=0,threads=1,warm_start=True,numeric_focus=1,lns_options=None):
    from solver_alns import adaptive_lns
    pipeline_started=time.perf_counter();total=float(total_core_time);deadline=pipeline_started+total;shares={"root":float(root_time_share),"warm":float(warm_start_time_share),"alns":float(alns_time_share),"main":float(main_bbc_time_share)}
    if total<=0 or any(v<0 for v in shares.values()):raise ValueError("total time and core time shares must be nonnegative")
    warm_time=total*shares["warm"];alns_budget=total*shares["alns"]
    if root_cut_time is None:
        used=sum(shares.values())
        if used>1+1e-9:raise ValueError("core time shares exceed total budget")
        root_time=total*shares["root"];main_time=total*(shares["main"]+max(0,1-used))
    else:
        root_time=float(root_cut_time);main_time=total-root_time-warm_time-alns_budget
        if min(root_time,main_time)<0:raise ValueError("explicit root time exceeds total core budget")
    active_concentration=bool(concentration_enabled and weights.master.concentration>0);pool=BendersCutPool();root_limit=min(root_time,remaining_time(deadline));phase0=root_lp_prepass(data,weights,pool,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,valid_inequality_profile=valid_inequality_profile,aggregate_recourse_lb=aggregate_recourse_lb,aggregate_relaxation_level=aggregate_relaxation_level,analytic_recourse_lb=analytic_recourse_lb,concentration_enabled=active_concentration,max_iters=root_cut_max_iters,time_limit=root_limit,relative_improvement_tol=root_cut_relative_improvement_tol,violation_tol=root_cut_violation_tol,stall_iters=root_cut_stall_iters) if root_prepass and root_limit>0 else {"disabled":True,"reason":"disabled" if not root_prepass else "global_deadline_exhausted","root_cut_count":0,"root_cut_runtime":0}
    warm_limit=min(warm_time,remaining_time(deadline));warm=_warm_start(data,weights,alloc_domain,warm_limit,add_valid_inequalities,active_concentration) if warm_start and warm_limit>0 else None;p1={"mode":"monolithic" if warm is not None else "no_incumbent" if warm_start else "disabled","enabled":bool(warm_start),"ok":warm is not None,"ub":None if warm is None else warm["ub"],"runtime":0.0 if not warm_start else warm_limit if warm is None else warm.get("runtime",0)}
    options=dict(lns_options or {});alns_limit=min(alns_budget,remaining_time(deadline));alns=adaptive_lns(data,weights,warm["solution"],time_limit=alns_limit,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=active_concentration,seed=seed,**options) if enable_alns and warm is not None and alns_limit>0 else {"start_ub":None if warm is None else warm["ub"],"best_ub":None if warm is None else warm["ub"],"improvement":0.0,"best_solution":None if warm is None else warm["solution"],"iterations":[],"operator_stats":{},"runtime":0.0,"disabled":True,"reason":"no feasible initialization" if warm is None else "disabled" if not enable_alns else "global_deadline_exhausted"}
    inherited_before=len(pool.records);main_time=remaining_time(deadline);p3=solve_bbc_phase(data,weights,time_limit=main_time,mip_gap=mip_gap,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,valid_inequality_profile=valid_inequality_profile,aggregate_recourse_lb=aggregate_recourse_lb,aggregate_relaxation_level=aggregate_relaxation_level,analytic_recourse_lb=analytic_recourse_lb,concentration_enabled=active_concentration,cut_strategy=cut_strategy,node_cuts=node_cuts,node_cut_limit=node_cut_limit,node_separation_policy=node_separation_policy,node_separation_interval=node_separation_interval,callback_time_share_limit=callback_time_share_limit,seed=seed+1,threads=threads,numeric_focus=numeric_focus,cut_pool=pool,start_solution=alns["best_solution"],origin_prefix="main",warm_start=False) if enable_phase3 and main_time>0 else {"ok":False,"disabled":True,"reason":"global_deadline_exhausted" if main_time<=0 else "disabled","lb":None,"runtime":0,"nodes":0}
    pipeline_trace=[];offset=0.0;root_trace=phase0.get("iteration_trace",[]);root_runtime=float(phase0.get("root_cut_runtime",0))
    for idx,item in enumerate(root_trace):pipeline_trace.append({"time":root_runtime*(idx+1)/max(1,len(root_trace)),"phase":"root","source":"completed_root_lp","ub":None,"lb":item.get("master_lp_obj")})
    offset+=root_runtime
    if warm is not None:pipeline_trace.append({"time":offset+float(warm.get("runtime",0)),"phase":"warm","source":"warm_incumbent","ub":warm["ub"],"lb":None})
    offset+=float(p1.get("runtime",0))
    for item in alns.get("anytime_trace",[]):pipeline_trace.append({**item,"time":offset+float(item["time"])})
    offset+=float(alns.get("runtime",0))
    for item in p3.get("anytime_trace",[]):pipeline_trace.append({**item,"time":offset+float(item["time"])})
    candidates=[]
    if warm is not None:candidates.append(("initialization",warm["ub"],warm["solution"]))
    if alns.get("best_solution") is not None:candidates.append(("alns",alns["best_ub"],alns["best_solution"]))
    if p3["ok"]:candidates.append(("main_bbc",p3["ub"],p3["solution"]))
    if not candidates:
        runtime=time.perf_counter()-pipeline_started;return {"anytime_trace":canonicalize(pipeline_trace,runtime,None,p3.get("lb")),"ok":False,"algorithm":"true_bbc_alns","workflow":"single_main_bbc","phase0_root_prepass":phase0,"phase1_initialization":p1,"phase1_bbc":p1,"phase2_alns":alns,"phase3_bbc":p3,"runtime":runtime}
    source,ub,solution=min(candidates,key=lambda x:x[1]);lb=p3.get("lb")
    if lb is not None and lb>ub+1e-5:raise AssertionError("pipeline LB exceeds UB")
    evaluation=evaluate_solution(data,weights,solution,alloc_domain=alloc_domain,concentration_enabled=active_concentration);con=evaluation["concentration"]
    runtime=time.perf_counter()-pipeline_started
    return {"anytime_trace":canonicalize(pipeline_trace,runtime,ub,lb),"ok":True,"algorithm":"true_bbc_alns_joint_bay_concentration","workflow":"single_main_bbc","runtime":runtime,"objective":{"open_weight":weights.master.x,"concentration_weight":weights.master.concentration,"distance_weight":weights.sub.dist,"balance_weight":weights.sub.balance,"conflict_weight":weights.sub.conflict},"concentration":{"mode":"joint_group_bay","available":con["available"],"enabled":con["enabled"],"status":con["status"],"raw_used_bays":con["raw_used_bays"],"normalized":con["normalized"],"cost":evaluation["concentration_cost"],"scale":con["scale"],"positive_ship_groups":len(con["positive_ship_groups"]),"used_bays_total":con["used_bays_total"]},"time_budget":{"total_core_time":total,"planned_root":root_time,"planned_warm":warm_time,"planned_alns":alns_budget,"main_bbc_actual_limit":main_time},"phase0_root_prepass":phase0,"phase1_initialization":p1,"phase1_bbc":p1,"phase2_alns":alns,"phase3_bbc":p3,"core_best":{"ub":ub,"lb":lb,"gap":None if lb is None else max(0,(ub-lb)/max(abs(ub),1e-9)),"components":evaluation,"solution":solution,"solution_source":source,"ub_source":"exact_first_stage_plus_global_recourse","lb_source":"benders_master_bound","feasibility_report":validate_solution(data,solution,alloc_domain=alloc_domain,add_valid_inequalities=add_valid_inequalities,concentration_enabled=active_concentration)},"cuts_inherited_by_phase3":inherited_before,"new_phase3_cuts":len(pool.records)-inherited_before,"total_unique_cuts":len(pool.records)}

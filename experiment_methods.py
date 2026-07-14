"""Adapters from method families to the common experiment result contract."""
from __future__ import annotations
from solution_evaluation import evaluate_common_solution
from solve_direct_gurobi import solve_direct_alns_pipeline,solve_direct_gurobi
from solver_true_benders import solve_bbc_phase,solve_true_benders_pipeline
from anytime import canonicalize

METHODS=("direct","direct_alns","bbc_candidate","bbc_core_verification","classical_benders")
def run_method(method,data,weights,configuration,*,budget,threads,mip_gap,alloc_domain,seed):
    if method=="direct":result=solve_direct_gurobi(data,weights,time_limit=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,seed=seed)
    elif method=="direct_alns":result=solve_direct_alns_pipeline(data,weights,total_time=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,seed=seed,lns_options=configuration.get("alns_parameters"))
    elif method=="bbc_core_verification":result=solve_bbc_phase(data,weights,time_limit=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,seed=seed,warm_start=False,add_valid_inequalities=False,aggregate_recourse_lb=False,analytic_recourse_lb=False,node_cuts=False,cut_strategy="standard")
    elif method=="classical_benders":
        from solver_classical_benders import solve_classical_benders
        result=solve_classical_benders(data,weights,time_limit=budget,mip_gap=mip_gap,threads=threads,alloc_domain=alloc_domain,seed=seed)
    elif method=="bbc_candidate":
        c=configuration;s=c["phase_shares"];result=solve_true_benders_pipeline(data,weights,total_core_time=budget,threads=threads,mip_gap=mip_gap,alloc_domain=alloc_domain,seed=seed,root_time_share=s["root"],warm_start_time_share=s["warm"],alns_time_share=s["alns"],main_bbc_time_share=s["main"],root_prepass=c["root_prepass"],warm_start=c["warm_start"],enable_alns=c["alns"],aggregate_recourse_lb=c["aggregate_recourse_lb"],aggregate_relaxation_level=c.get("aggregate_relaxation_level","size"),analytic_recourse_lb=c["analytic_recourse_lb"],add_valid_inequalities=c["valid_inequalities"],valid_inequality_profile=c.get("valid_inequality_profile","common"),node_cuts=c["node_cuts"],cut_strategy=c["cut_strategy"],lns_options=c["alns_parameters"])
    else:raise KeyError(f"unknown method {method!r}")
    if not result.get("anytime_trace"):
        elapsed=0.0;points=[]
        for item in result.get("iteration_trace",[]):
            elapsed+=float(item.get("master_runtime",0))+float(item.get("sp_runtime",0));points.append({"time":elapsed,"phase":"main","source":"classical_iteration","ub":item.get("ub"),"lb":item.get("lb")})
        best=result.get("core_best",result);result["anytime_trace"]=canonicalize(points,result.get("runtime",budget),best.get("ub"),best.get("lb"))
    solution=result.get("solution") or result.get("core_best",{}).get("solution");evaluation=evaluate_common_solution(data,weights,solution,alloc_domain=alloc_domain) if solution else None
    if solution and not evaluation["feasibility"]["feasible"]:raise RuntimeError(f"method returned infeasible solution: {evaluation['feasibility']}")
    return result,solution,evaluation

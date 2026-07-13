from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_monolithic import build_monolithic_model,extract_solution
from solve_direct_gurobi import solve_direct_gurobi
from solver_alns import adaptive_lns
from solver_classical_benders import solve_classical_benders
from solver_true_benders import solve_bbc_phase

def assert_trace(result):
 t=result["anytime_trace"];assert len(t)>=2 and t[-1]["phase"]=="final";assert all(a["time"]<=b["time"] for a,b in zip(t,t[1:]));ubs=[x["ub"] for x in t if x["ub"] is not None];lbs=[x["lb"] for x in t if x["lb"] is not None];assert all(a>=b for a,b in zip(ubs,ubs[1:]));assert all(a<=b for a,b in zip(lbs,lbs[1:]));assert t[-1]["ub"]==result.get("ub",result.get("best_ub"));assert t[-1]["lb"]==result.get("lb")

def test_all_methods_emit_non_final_only_trace():
 d=prepare_instance(get_data_tiny_benders());w=Weights();direct=solve_direct_gurobi(d,w,time_limit=5,mip_gap=0);assert_trace(direct)
 classical=solve_classical_benders(d,w,time_limit=8,mip_gap=0);assert_trace(classical)
 bbc=solve_bbc_phase(d,w,time_limit=8,mip_gap=0,aggregate_recourse_lb=False,analytic_recourse_lb=False);assert_trace(bbc)
 m,v,_=build_monolithic_model(d,w);m.optimize();alns=adaptive_lns(d,w,extract_solution(v),time_limit=.15,repair_time=.05,min_repair_time=.02,max_repair_time=.05);assert_trace(alns);m.dispose()

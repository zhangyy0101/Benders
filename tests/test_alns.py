from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution
from solver_alns import adaptive_lns,solve_attribute_refinement
def start():
 d=prepare_instance(get_data_tiny_benders());m,v,_=build_monolithic_model(d,Weights());m.optimize();return d,extract_solution(v)
def test_alns_solution_feasible_in_monolithic_model():
 d,s=start();r=adaptive_lns(d,Weights(),s,time_limit=.1);assert r['best_ub']<=evaluate_solution(d,Weights(),s)['core_cost']+1e-6
def test_refinement_respects_core_cap():
 d,s=start();ub=evaluate_solution(d,Weights(),s)['core_cost'];r=solve_attribute_refinement(d,Weights(),s,ub,time_limit=2);assert r['candidate_core_cost']<=ub*1.01+1e-5
def test_refined_solution_not_used_for_core_gap():
 d,s=start();ub=evaluate_solution(d,Weights(),s)['core_cost'];r=solve_attribute_refinement(d,Weights(),s,ub,time_limit=2);assert ub==16000

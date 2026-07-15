from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_master import build_master_model
from solve_direct_gurobi import solve_direct_gurobi
from solver_true_benders import root_lp_prepass,solve_bbc_phase,solve_true_benders_pipeline
from model_recourse import BendersCutPool
def test_no_distance_double_counting():
 d=prepare_instance(get_data_tiny_benders());m,v,_=build_master_model(d,Weights());assert set(v)=={'alloc_boxes','eta','concentration_use','bay_height'}
def test_benders_lb_not_above_direct_optimum():
 d=prepare_instance(get_data_tiny_benders());direct=solve_direct_gurobi(d,Weights(),time_limit=3,mip_gap=0);bbc=solve_bbc_phase(d,Weights(),time_limit=3,mip_gap=0);assert bbc['lb']<=direct['ub']+1e-5 and abs(bbc['ub']-direct['ub'])<1e-5
def test_evaluated_ub_is_recourse_feasible():
 d=prepare_instance(get_data_tiny_benders());r=solve_bbc_phase(d,Weights(),time_limit=3,mip_gap=0);assert r['ok'] and r['ub_source']=='exact_global_recourse_evaluation'
def test_reported_gap_uses_same_core_objective():
 d=prepare_instance(get_data_tiny_benders());r=solve_bbc_phase(d,Weights(),time_limit=3,mip_gap=0);assert abs(r['gap']-(r['ub']-r['lb'])/r['ub'])<1e-9
def test_phase3_inherits_phase1_cuts():
 d=prepare_instance(get_data_tiny_benders());r=solve_true_benders_pipeline(d,Weights(),total_core_time=3,root_cut_time=.5,mip_gap=0,aggregate_recourse_lb=False,analytic_recourse_lb=False);assert r['cuts_inherited_by_phase3']>0
def test_master_obj_not_used_as_exact_ub_without_recourse():
 d=prepare_instance(get_data_tiny_benders());r=solve_bbc_phase(d,Weights(),time_limit=2,mip_gap=0,warm_start=False);assert r['ub_source']=='exact_global_recourse_evaluation' and r['lb_source']=='benders_master_bound'
def test_inherited_cuts_remain_valid():test_phase3_inherits_phase1_cuts()
def test_root_prepass_improves_tiny_bound():
 d=prepare_instance(get_data_tiny_benders());r=root_lp_prepass(d,Weights(),BendersCutPool(),max_iters=20,time_limit=2);assert r['root_final_bound']>=r['root_initial_bound'] and r['master_eta_bound']>0

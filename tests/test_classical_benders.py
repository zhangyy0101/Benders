import inspect
import pytest
from benchmark_io import load_instance
from config import Weights
from cut_validation import validate_optimality_cut
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_master import build_master_model,extract_master_point
from model_recourse import GlobalRecourseOracle
from solve_direct_gurobi import solve_direct_gurobi
from solver_classical_benders import relative_gap,solve_classical_benders

pytestmark=pytest.mark.gurobi

def test_gap_formula_and_no_callback_implementation():
    assert relative_gap(100,90)==pytest.approx(.1);assert relative_gap(None,0) is None
    source=inspect.getsource(solve_classical_benders)
    assert "cbLazy" not in source and "optimize(callback" not in source

@pytest.mark.parametrize("name",["tiny","tiny_concentration"])
def test_classical_matches_direct_exact_on_tiny(name):
    data=prepare_instance(build_builtin_instance(name));direct=solve_direct_gurobi(data,Weights(),time_limit=10,mip_gap=0,threads=1);classical=solve_classical_benders(data,Weights(),time_limit=10,mip_gap=0,threads=1)
    assert classical["status_name"]=="OPTIMAL" and classical["termination_reason"]=="optimal"
    assert classical["components"]["feasibility"]["feasible"]
    assert classical["lb"]<=classical["ub"]+1e-6
    assert classical["ub"]==pytest.approx(direct["ub"],abs=1e-5)
    assert classical["used_callback"] is False and not any(classical["strengthening"].values())
    assert classical["iteration_trace"] and classical["sp_statistics"]["sp_solve_count"]>0

def test_classical_s01_is_feasible_and_matches_direct_if_optimal():
    data=prepare_instance(load_instance("benchmarks/paper_exp_v1_pilot21/small/S01.json"));direct=solve_direct_gurobi(data,Weights(),time_limit=60,mip_gap=0,threads=1);classical=solve_classical_benders(data,Weights(),time_limit=60,mip_gap=0,threads=1)
    assert classical["ok"] and classical["components"]["feasibility"]["feasible"]
    assert classical["lb"]<=classical["ub"]+1e-5
    if direct["status_name"]==classical["status_name"]=="OPTIMAL":assert classical["ub"]==pytest.approx(direct["ub"],abs=1e-5)

def test_generated_optimality_cut_is_valid_and_tight():
    data=prepare_instance(build_builtin_instance("tiny"));master,variables,_=build_master_model(data,Weights(),add_valid_inequalities=False,aggregate_recourse_lb=False,analytic_recourse_lb=False);master.optimize();point=extract_master_point(variables);oracle=GlobalRecourseOracle(data,Weights());oracle.update_rhs(point["x"],point["alloc_boxes"]);oracle.solve();cut=oracle.build_optimality_cut(point,"classical_test");point["eta"]=oracle.objective_value();assert abs(cut.value_at(point))<1e-6 and validate_optimality_cut(data,Weights(),cut,[point])["valid"]

def test_iteration_limit_is_not_reported_optimal():
    data=prepare_instance(build_builtin_instance("tiny"));result=solve_classical_benders(data,Weights(),time_limit=10,max_iterations=1)
    assert result["status_name"]!="OPTIMAL" and result["termination_reason"]=="iteration_limit"

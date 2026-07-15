import pytest
from config import Weights
from data import get_data_tiny_benders,prepare_instance
from deterministic_initializer import build_deterministic_initial_solution
from model_master import build_master_model
from model_recourse import GlobalRecourseOracle

def test_initializer_is_deterministic_and_feasible():
    data=prepare_instance(get_data_tiny_benders());a=build_deterministic_initial_solution(data,Weights());b=build_deterministic_initial_solution(data,Weights())
    assert a is not None and b is not None
    assert a["solution"]["alloc_boxes"]==b["solution"]["alloc_boxes"]
    assert a["ub"]==pytest.approx(b["ub"],abs=1e-9)

def test_group_aggregate_equals_global_recourse_at_fixed_allocation():
    data=prepare_instance(get_data_tiny_benders());weights=Weights();initial=build_deterministic_initial_solution(data,weights);alloc=initial["solution"]["alloc_boxes"]
    master,variables,context=build_master_model(data,weights,analytic_recourse_lb=False)
    for key,var in variables["alloc_boxes"].items():var.LB=var.UB=alloc[key]
    master.optimize();oracle=GlobalRecourseOracle(data,weights);oracle.update_rhs(alloc);oracle.solve()
    assert context["aggregate"]["aggregate_objective"].getValue()==pytest.approx(oracle.objective_value(),abs=1e-6)

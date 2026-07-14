import pytest
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_monolithic import build_monolithic_model, extract_solution
from solver_true_benders import solve_bbc_phase


@pytest.mark.gurobi
def test_agfr_start_trace_is_repair_not_warm():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    model, variables, _ = build_monolithic_model(data, Weights(), add_valid_inequalities=False)
    model.Params.OutputFlag = 0
    model.optimize()
    result = solve_bbc_phase(data, Weights(), time_limit=1, add_valid_inequalities=False,
        start_solution=extract_solution(variables), start_solution_source="agfr", warm_start=False)
    first = next(item for item in result["anytime_trace"] if item.get("ub") is not None)
    assert first["phase"] == "repair"
    assert first["source"] == "agfr_incumbent"
    assert all(item["time"] >= 0 for item in result["anytime_trace"])

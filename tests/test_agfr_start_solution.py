import pytest
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_monolithic import build_monolithic_model, extract_solution
from solver_true_benders import solve_bbc_phase


@pytest.mark.gurobi
def test_agfr_start_seeds_cache_cut_and_cutoff():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    model, variables, _ = build_monolithic_model(data, Weights(), add_valid_inequalities=False)
    model.Params.OutputFlag = 0
    model.optimize()
    result = solve_bbc_phase(data, Weights(), time_limit=2, mip_gap=0,
        add_valid_inequalities=False, start_solution=extract_solution(variables),
        start_solution_source="agfr", warm_start=False)
    stats = result["cut_statistics"]
    assert stats["cache_seeded_entries"] == 1
    assert abs(stats["initial_cut_tightness"]) <= 1e-5
    assert stats["initial_cutoff"] > 0
    assert stats["start_solution_source"] == "agfr"

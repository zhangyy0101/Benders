import pytest

from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from solution_evaluation import evaluate_common_solution
from solve_direct_gurobi import solve_direct_gurobi
from solver_alns import adaptive_lns
from solver_true_benders import solve_bbc_phase

pytestmark = pytest.mark.gurobi


def fixture():
    return prepare_instance(build_builtin_instance("tiny_concentration"))


def test_direct_model_and_common_evaluator_match():
    data = fixture()
    result = solve_direct_gurobi(data, Weights(), time_limit=4, mip_gap=0, threads=1)
    common = evaluate_common_solution(data, Weights(), result["solution"])
    assert common == result["components"]
    assert common["feasibility"]["feasible"]
    assert abs(result["ub"] - common["objective"]["total"]) < 1e-5


def test_direct_alns_and_bbc_use_identical_evaluator_schema():
    data = fixture()
    direct = solve_direct_gurobi(data, Weights(), time_limit=4, mip_gap=0, threads=1)
    alns = adaptive_lns(data, Weights(), direct["solution"], time_limit=.1, repair_time=.05, seed=2)
    bbc = solve_bbc_phase(data, Weights(), time_limit=4, mip_gap=0, threads=1)
    evaluations = [
        evaluate_common_solution(data, Weights(), direct["solution"]),
        evaluate_common_solution(data, Weights(), alns["best_solution"]),
        evaluate_common_solution(data, Weights(), bbc["solution"]),
    ]
    assert all(set(value) == set(evaluations[0]) for value in evaluations)
    assert all(value["feasibility"]["feasible"] for value in evaluations)
    assert bbc["ub"] == pytest.approx(evaluations[2]["core_cost"], abs=1e-5)

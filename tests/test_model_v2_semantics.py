import copy

import pytest

from config import PROBLEM_PROTOCOL,Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_common import required_reserve
from model_monolithic import build_monolithic_model,extract_solution
from solution_evaluation import evaluate_common_solution


def test_alpha_does_not_change_integer_allocations_or_objective():
    raw = build_builtin_instance("tiny")
    first = prepare_instance(copy.deepcopy(raw));first["Alpha"] = 1.0
    second = prepare_instance(copy.deepcopy(raw));second["Alpha"] = 9.0
    assert required_reserve(first, "J1", "G20", 1, "integer") == 4
    assert required_reserve(second, "J1", "G20", 1, "integer") == 4
    objectives = []
    for data in (first, second):
        model, variables, _ = build_monolithic_model(data, Weights())
        model.Params.OutputFlag = 0;model.optimize();objectives.append(model.ObjVal)
        assert all(abs(v.X-round(v.X)) <= 1e-6 for v in variables["alloc_boxes"].values())
    assert objectives[0] == pytest.approx(objectives[1])


def test_x_is_an_activation_kpi_with_zero_objective_cost():
    data = prepare_instance(build_builtin_instance("tiny"))
    model, variables, context = build_monolithic_model(data, Weights())
    model.Params.OutputFlag = 0;model.optimize()
    evaluation = evaluate_common_solution(data, Weights(), extract_solution(variables))
    assert evaluation["open_raw"] > 0
    assert evaluation["components"]["open"]["weighted"] == 0
    assert context["open_objective"].size() == 0


def test_prepare_preserves_and_scales_instance_handling_rates():
    raw = build_builtin_instance("tiny")
    raw["Bay_Handling_Rate"] = {(i,n):50.0 for i in raw["I_list"] for n in raw["N"]}
    key = next(iter(raw["Bay_Handling_Rate"]));raw["Bay_Handling_Rate"][key] = 37.0
    data = prepare_instance(raw, handling_rate_scale=1.5)
    assert data["Bay_Handling_Rate"][key] == pytest.approx(55.5)
    assert data["handling_rate_source"] == "instance_scaled"
    assert PROBLEM_PROTOCOL == "paper-exp-v2-integer-allocation-no-alpha-no-open"

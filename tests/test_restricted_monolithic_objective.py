from config import Weights
from data import get_data_tiny_benders, prepare_instance
from model_common import group_size, ship_groups
from model_monolithic import build_restricted_monolithic_model, extract_solution
from solution_evaluation import evaluate_common_solution


def test_restricted_objective_is_exact_original_objective():
    data = prepare_instance(get_data_tiny_benders())
    allowed = {(j, g): [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == group_size(data, g)]
               for j in data["J_new"] for g in ship_groups(data, j)}
    model, variables, _ = build_restricted_monolithic_model(data, Weights(), allowed)
    try:
        model.optimize()
        evaluation = evaluate_common_solution(data, Weights(), extract_solution(variables))
        assert abs(model.ObjVal - evaluation["core_cost"]) <= 1e-5
    finally:
        model.dispose()

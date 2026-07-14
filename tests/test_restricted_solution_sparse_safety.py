from config import Weights
from data import get_data_tiny_benders, prepare_instance
from model_common import group_size, ship_groups
from model_monolithic import build_restricted_monolithic_model, extract_solution
from solution_evaluation import evaluate_common_solution
from solution_validation import validate_solution


def test_sparse_solution_is_checker_and_evaluator_safe():
    data = prepare_instance(get_data_tiny_benders())
    allowed = {(j, g): [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == group_size(data, g)]
               for j in data["J_new"] for g in ship_groups(data, j)}
    model, variables, _ = build_restricted_monolithic_model(data, Weights(), allowed)
    try:
        model.optimize()
        solution = extract_solution(variables)
        assert len(solution["alloc_boxes"]) < len(data["I_list"]) * sum(len(ship_groups(data, j)) for j in data["J_new"]) * len(data["N"])
        assert validate_solution(data, solution)["feasible"]
        assert evaluate_common_solution(data, Weights(), solution)["feasibility"]["feasible"]
    finally:
        model.dispose()

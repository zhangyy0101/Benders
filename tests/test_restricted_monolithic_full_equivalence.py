import pytest

from benchmark_io import load_instance
from config import Weights
from data import get_data_tiny_benders, get_data_tiny_concentration, prepare_instance
from model_common import group_size, ship_groups
from model_monolithic import build_monolithic_model, build_restricted_monolithic_model, extract_solution
from solution_evaluation import evaluate_common_solution
from solution_validation import validate_solution


def full_domain(data):
    return {(j, g): [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == group_size(data, g)]
            for j in data["J_new"] for g in ship_groups(data, j)}


@pytest.mark.parametrize("raw", [get_data_tiny_benders(), get_data_tiny_concentration(),
                                  load_instance("benchmarks/paper_exp_v1_pilot21_exact/XS01.json")])
def test_full_compatible_restriction_matches_full_monolithic(raw):
    data = prepare_instance(raw)
    full, full_vars, full_ctx = build_monolithic_model(data, Weights())
    restricted, restricted_vars, restricted_ctx = build_restricted_monolithic_model(data, Weights(), full_domain(data))
    try:
        compatible_keys = {key for key in full_vars["alloc_boxes"] if key[0] in full_domain(data)[key[1], key[2]]}
        assert set(restricted_vars["alloc_boxes"]) == compatible_keys
        for key, variable in restricted_vars["alloc_boxes"].items():
            assert variable.VType == full_vars["alloc_boxes"][key].VType
            assert variable.LB == full_vars["alloc_boxes"][key].LB
        full.Params.OutputFlag = restricted.Params.OutputFlag = 0
        full.Params.TimeLimit = restricted.Params.TimeLimit = 15
        full.optimize(); restricted.optimize()
        assert full.SolCount and restricted.SolCount
        assert abs(full.ObjVal - restricted.ObjVal) <= 1e-5
        fs, rs = extract_solution(full_vars), extract_solution(restricted_vars)
        assert validate_solution(data, fs)["feasible"] and validate_solution(data, rs)["feasible"]
        fe, re = evaluate_common_solution(data, Weights(), fs), evaluate_common_solution(data, Weights(), rs)
        for name in ("open_cost", "concentration_cost", "distance_cost", "balance_cost", "conflict_cost"):
            assert abs(fe[name] - re[name]) <= 1e-5
        assert full_ctx["concentration_context"]["scale"] == restricted_ctx["concentration_context"]["scale"]
    finally:
        full.dispose(); restricted.dispose()

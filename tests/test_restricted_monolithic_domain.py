from config import Weights
from data import get_data_tiny_benders, prepare_instance
from model_common import ship_groups
from model_monolithic import build_restricted_monolithic_model


def one_bay_domain(data):
    return {(j, g): [next(i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == data["GroupSize"][g])]
            for j in data["J_new"] for g in ship_groups(data, j)}


def test_restricted_variables_only_use_allowed_group_bays():
    data = prepare_instance(get_data_tiny_benders())
    allowed = one_bay_domain(data)
    model, variables, context = build_restricted_monolithic_model(data, Weights(), allowed)
    try:
        assert all(i in allowed[j, g] for i, j, g, _n in variables["alloc_boxes"])
        assert all(i in allowed[j, g] for j, g, i, _n in variables["din"])
        assert context["restricted_variable_count"] < context["estimated_full_variable_count"]
        assert context["candidate_pair_ratio"] < 1
    finally:
        model.dispose()

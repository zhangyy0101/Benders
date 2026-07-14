from config import Weights
from data import get_data_tiny_concentration, prepare_instance
from model_common import group_size, ship_groups
from model_concentration import concentration_metadata
from model_monolithic import build_restricted_monolithic_model


def test_restricted_concentration_uses_candidates_but_full_scale():
    data = prepare_instance(get_data_tiny_concentration())
    allowed = {(j, g): [next(i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == group_size(data, g))]
               for j in data["J_new"] for g in ship_groups(data, j)}
    model, variables, context = build_restricted_monolithic_model(data, Weights(), allowed)
    try:
        assert all(i in allowed[j, g] for j, g, i in variables["concentration_use"])
        assert context["concentration_context"]["scale"] == concentration_metadata(data)["scale"]
    finally:
        model.dispose()

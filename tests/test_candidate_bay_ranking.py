from candidate_domain import build_candidate_domain
from data import get_data_tiny_benders, prepare_instance


def test_fractional_alloc_and_x_support_rank_first():
    data = prepare_instance(get_data_tiny_benders())
    j, group = data["J_new"][0], data["G"][0]
    bay = next(i for i in reversed(data["I_list"]) if data["Fixed_Bay_Mode"][i] == data["GroupAttrs"][group]["size"])
    guide = {"source": "lp_fallback", "diagnostics": {
        "aggregate_flow_by_ship_size_block": {},
        "alloc_support_by_ship_group_bay": {(j, group, bay): {"max": .25, "sum": .75}},
        "x_support_by_ship_bay": {(j, bay): .5},
    }}
    result = build_candidate_domain(data, guide)
    assert result["scores"]["bay_rankings"][j, group][0] == bay
    assert bay in result["candidate_bays"][j, group]

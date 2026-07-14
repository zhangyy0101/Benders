from candidate_domain import build_candidate_domain
from data import get_data_tiny_benders, prepare_instance


def test_large_group_expands_beyond_one_bay_for_individual_coverage():
    data = prepare_instance(get_data_tiny_benders())
    result = build_candidate_domain(data, {"source": "static_fallback", "diagnostics": {}},
                                    min_bays_per_group=1, max_bays_per_group=1, max_candidate_fraction=.1)
    assert result["diagnostics"]["individual_coverage_pass"]
    assert all(result["candidate_bays"].values())


def test_soft_cap_can_be_broken_by_required_guide_support():
    data = prepare_instance(get_data_tiny_benders())
    j, group = data["J_new"][0], data["G"][0]
    compatible = [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == data["GroupAttrs"][group]["size"]]
    guide = {"source": "mip_incumbent", "diagnostics": {
        "aggregate_flow_by_ship_size_block": {}, "x_support_by_ship_bay": {},
        "alloc_support_by_ship_group_bay": {(j, group, i): {"max": 1.0, "sum": 1.0} for i in compatible},
    }}
    result = build_candidate_domain(data, guide, min_bays_per_group=1, max_bays_per_group=1, max_candidate_fraction=.1)
    assert set(compatible) <= set(result["candidate_bays"][j, group])
    assert result["diagnostics"]["forced_soft_cap_exceptions"]

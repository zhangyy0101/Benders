from candidate_domain import build_candidate_domain
from data import get_data_tiny_benders, prepare_instance


def static_guide():
    return {"source": "static_fallback", "diagnostics": {}}


def test_no_guide_support_has_stable_nonempty_ship_size_blocks():
    data = prepare_instance(get_data_tiny_benders())
    result = build_candidate_domain(data, static_guide())
    assert result["candidate_blocks"]
    assert all(blocks for blocks in result["candidate_blocks"].values())
    assert result["diagnostics"]["individual_coverage_pass"]


def test_positive_alloc_block_is_preserved_outside_top_z():
    data = prepare_instance(get_data_tiny_benders())
    j, group = data["J_new"][0], data["G"][0]
    size = data["GroupAttrs"][group]["size"]
    compatible = [i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == size]
    bay = compatible[-1]
    block = data["I"][bay]["block"]
    other = next(k for k in data["K"] if k != block)
    guide = {"source": "mip_incumbent", "diagnostics": {
        "aggregate_flow_by_ship_size_block": {(j, size, other): 100.0},
        "alloc_support_by_ship_group_bay": {(j, group, bay): {"max": 1.0, "sum": 1.0}},
        "x_support_by_ship_bay": {},
    }}
    result = build_candidate_domain(data, guide, min_blocks_per_ship_size=1, max_blocks_per_ship_size=1)
    assert block in result["candidate_blocks"][j, size]

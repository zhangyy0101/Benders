from candidate_domain import build_candidate_domain
from data import get_data_tiny_benders, prepare_instance


def test_level_one_adds_blocks_and_two_bays_where_available():
    data = prepare_instance(get_data_tiny_benders())
    guide = {"source": "static_fallback", "diagnostics": {}}
    level0 = build_candidate_domain(data, guide, min_blocks_per_ship_size=1, max_blocks_per_ship_size=1, min_bays_per_group=1)
    level1 = build_candidate_domain(data, guide, min_blocks_per_ship_size=1, max_blocks_per_ship_size=1, min_bays_per_group=1, expansion_level=1)
    assert all(set(level0["candidate_blocks"][key]) <= set(value) for key, value in level1["candidate_blocks"].items())
    assert all(set(level0["candidate_bays"][key]) <= set(value) for key, value in level1["candidate_bays"].items())


def test_level_two_rejects_no_valid_level_and_is_monotone():
    data = prepare_instance(get_data_tiny_benders())
    guide = {"source": "static_fallback", "diagnostics": {}}
    one = build_candidate_domain(data, guide, expansion_level=1)
    two = build_candidate_domain(data, guide, expansion_level=2)
    assert all(set(one["candidate_bays"][key]) <= set(value) for key, value in two["candidate_bays"].items())

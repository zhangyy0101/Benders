from candidate_domain import build_candidate_domain
from config import Weights
from data import get_data_tiny_benders, prepare_instance
from solver_aggregate_guide import solve_aggregate_guide


def test_candidate_domain_is_deterministic():
    data = prepare_instance(get_data_tiny_benders())
    guide = solve_aggregate_guide(data, Weights(), time_limit=1, seed=3)
    a = build_candidate_domain(data, guide)
    b = build_candidate_domain(data, guide)
    assert a["candidate_blocks"] == b["candidate_blocks"]
    assert a["candidate_bays"] == b["candidate_bays"]
    assert a["candidate_ship_bays"] == b["candidate_ship_bays"]
    assert a["diagnostics"]["candidate_pair_ratio"] == b["diagnostics"]["candidate_pair_ratio"]

from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration
from config import Weights
from data import get_data_tiny_benders, prepare_instance
from solver_aggregate_guide import solve_aggregate_guide


def test_mip_incumbent_is_extracted_without_ub_claim():
    data = prepare_instance(get_data_tiny_benders())
    result = solve_aggregate_guide(data, Weights(), time_limit=2, seed=7)
    assert result["ok"] and result["source"] == "mip_incumbent"
    assert result["x"] and result["alloc_boxes"] and result["aggregate_z"]
    assert "ub" not in result and "upper" not in " ".join(result)
    assert result["guide_objective"] is not None


def test_fixed_seed_is_deterministic_on_tiny():
    data = prepare_instance(get_data_tiny_benders())
    a = solve_aggregate_guide(data, Weights(), time_limit=2, seed=11)
    b = solve_aggregate_guide(data, Weights(), time_limit=2, seed=11)
    assert a["source"] == b["source"]
    assert a["x"] == b["x"]
    assert a["alloc_boxes"] == b["alloc_boxes"]
    assert a["aggregate_z"] == b["aggregate_z"]


def test_candidate_v1_hash_is_unchanged():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    assert config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH

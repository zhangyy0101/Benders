from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH, resolved_algorithm_label
from algorithm_configurations import get_algorithm_configuration


def test_candidate_v1_uses_implicit_size_and_common_defaults_without_hash_change():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    assert config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH
    assert config.get("aggregate_relaxation_level", "size") == "size"
    assert config.get("valid_inequality_profile", "common") == "common"
    assert "aggregate_relaxation_level" not in config
    assert "valid_inequality_profile" not in config
    assert resolved_algorithm_label(config) == "aggregate_strengthened_bbc"

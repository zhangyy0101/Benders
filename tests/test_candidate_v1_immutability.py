from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH, configuration_hash, configuration_payload
from algorithm_configurations import get_algorithm_configuration


def test_candidate_v1_payload_and_hash_are_immutable():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    assert config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH
    assert configuration_hash(configuration_payload(config)) == FROZEN_CANDIDATE_V1_HASH
    assert config["aggregate_recourse_lb"] is True
    assert config["phase_shares"] == {"root": 0.0, "warm": 0.0, "alns": 0.0, "main": 1.0}
    assert not any(config[key] for key in ("analytic_recourse_lb", "root_prepass", "warm_start", "alns", "valid_inequalities", "node_cuts"))
    assert "aggregate_relaxation_level" not in config
    assert "valid_inequality_profile" not in config

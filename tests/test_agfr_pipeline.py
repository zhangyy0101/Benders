from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration


def test_candidate_v1_stays_repair_free_and_hash_stable():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    assert config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH
    assert "primal_repair" not in config
    assert "primal_repair_method" not in config


def test_agfr_candidate_has_only_repair_and_main_enabled():
    config = get_algorithm_configuration("candidate-v2-agfr-development")
    assert config["primal_repair"] is True
    assert config["primal_repair_method"] == "aggregate_guided_fix_and_repair"
    assert not any(config[key] for key in ("root_prepass", "warm_start", "alns", "valid_inequalities"))
    assert config["phase_shares"] == {"root": 0.0, "warm": 0.0, "alns": 0.0, "main": 1.0}

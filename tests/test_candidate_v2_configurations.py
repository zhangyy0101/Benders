from algorithm_configurations import get_algorithm_configuration


def test_candidate_v2_development_configurations_are_isolated():
    expected = {
        "V2A_valid": ("size", True),
        "V2B_pod_size_aggregate": ("pod_size", False),
        "V2C_pod_size_aggregate_valid": ("pod_size", True),
    }
    hashes = set()
    for name, (level, valid) in expected.items():
        config = get_algorithm_configuration(name)
        assert config["configuration_version"] == "2-dev"
        assert config["status"] == "development_candidate_v2"
        assert config["base"] == "algorithm-candidate-v1"
        assert config["aggregate_relaxation_level"] == level
        assert config["valid_inequalities"] is valid
        assert not any(config[key] for key in ("analytic_recourse_lb", "root_prepass", "warm_start", "alns", "node_cuts"))
        hashes.add(config["configuration_hash"])
    assert len(hashes) == 3

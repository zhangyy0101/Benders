import pytest

from algorithm_configuration import validate_algorithm_configuration
from algorithm_configurations import get_algorithm_configuration


def changed(**updates):
    config = get_algorithm_configuration("C0_bbc_core")
    config.pop("configuration_hash")
    config.update(updates)
    return config


def test_backward_compatible_defaults_are_not_written_back():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    validate_algorithm_configuration(config)
    assert "aggregate_relaxation_level" not in config and "valid_inequality_profile" not in config


@pytest.mark.parametrize("updates", [
    {"aggregate_relaxation_level": "pod"},
    {"valid_inequality_profile": "unknown"},
    {"phase_shares": {"root": -.1, "warm": 0, "alns": 0, "main": 1}},
    {"phase_shares": {"root": .2, "warm": .2, "alns": .2, "main": .5}},
    {"alns": True, "warm_start": False},
])
def test_invalid_configuration_rejected(updates):
    with pytest.raises(ValueError):
        validate_algorithm_configuration(changed(**updates))

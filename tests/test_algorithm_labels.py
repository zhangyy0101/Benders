from algorithm_configuration import resolved_algorithm_label
from algorithm_configurations import get_algorithm_configuration


def test_candidate_v1_label_is_not_alns():
    label = resolved_algorithm_label(get_algorithm_configuration("algorithm-candidate-v1"))
    assert label == "aggregate_strengthened_bbc" and "alns" not in label


def test_legacy_full_label_is_explicitly_legacy():
    assert resolved_algorithm_label(get_algorithm_configuration("bbc_full_current")) == "true_bbc_alns_legacy"


def test_future_fields_use_backward_compatible_label_resolution():
    config = get_algorithm_configuration("C2_core_aggregate")
    config.update(configuration_name="development-v2", aggregate_relaxation_level="pod_size")
    assert resolved_algorithm_label(config) == "pod_size_aggregate_strengthened_bbc"

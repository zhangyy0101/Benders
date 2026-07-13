from scripts.run_adaptive_confirmation import normalized_improvement, selected_configs
from algorithm_configurations import get_algorithm_configuration


def test_normalized_improvement_directions():
    candidate = {"optimization": {"ub": 90.0, "lb": 60.0}}
    baseline = {"optimization": {"ub": 100.0, "lb": 50.0}}
    assert normalized_improvement(candidate, baseline, "ub") > 0
    assert normalized_improvement(candidate, baseline, "lb") > 0


def test_p2_selection_has_required_size():
    configs = selected_configs("experiments/internal_screen_fast/recommended_configs.json")
    assert 4 <= len(configs) <= 6


def test_frozen_candidate_respects_structure_limit():
    config = get_algorithm_configuration("algorithm-candidate-v1")
    assert config["status"] == "frozen_candidate"
    assert config["aggregate_recourse_lb"]
    assert not any(config[key] for key in ("analytic_recourse_lb", "root_prepass", "warm_start", "alns", "valid_inequalities"))

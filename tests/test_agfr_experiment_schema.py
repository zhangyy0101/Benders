from algorithm_configurations import get_algorithm_configuration
from experiment_runner import execute_run
from tests.test_experiment_runner import fixture_job


def test_experiment_exposes_repair_and_separate_timing(tmp_path):
    config = get_algorithm_configuration("candidate-v2-agfr-development")
    job = fixture_job(tmp_path, "bbc_candidate", config)
    def runner(*args, **kwargs):
        repair = {"enabled": True, "method": "aggregate_guided_fix_and_repair", "ok": False,
                  "runtime": .2, "guide_runtime": .05, "fallback_reason": "NO_INCUMBENT"}
        raw = {"status_name": "MOCK", "runtime": .3, "ub": 1, "lb": 0, "gap": 1,
               "nodes": 0, "phase_primal_repair": repair, "anytime_trace": []}
        return raw, {"x": {}}, {"feasibility": {"feasible": True}, "core_cost": 1}
    result = execute_run(**job, output=tmp_path, method_runner=runner)
    assert result["repair"]["method"] == "aggregate_guided_fix_and_repair"
    assert result["timing"]["repair"] == .2
    assert result["timing"]["guide"] == .05
    assert result["timing"]["warm"] is None and result["timing"]["alns"] is None

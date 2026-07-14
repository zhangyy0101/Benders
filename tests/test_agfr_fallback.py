import pytest
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
import solver_fix_and_repair
import solver_true_benders as stb


@pytest.mark.gurobi
def test_agfr_failure_falls_through_to_main_bbc(monkeypatch):
    failure = {"ok": False, "status_name": "NO_INCUMBENT", "runtime": 0.0,
        "ub": None, "solution": None, "guide": {}, "candidate_domain": None,
        "repair_attempts": [], "selected_attempt": None, "oracle_consistent": None,
        "anytime_trace": []}
    monkeypatch.setattr(solver_fix_and_repair, "solve_aggregate_guided_fix_and_repair",
                        lambda *args, **kwargs: failure)
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    result = stb.solve_true_benders_pipeline(data, Weights(), total_core_time=1,
        root_prepass=False, warm_start=False, enable_alns=False,
        add_valid_inequalities=False, primal_repair=True)
    assert result["phase_primal_repair"]["ok"] is False
    assert result["phase_primal_repair"]["fallback_reason"] == "NO_INCUMBENT"
    assert result["ok"] and result["core_best"]["solution_source"] == "main_bbc"

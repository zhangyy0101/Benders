import pytest

from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from solver_true_benders import solve_bbc_then_repair_pipeline


@pytest.mark.gurobi
def test_post_bbc_repair_preserves_bound_and_returns_checked_ub():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    result = solve_bbc_then_repair_pipeline(
        data, Weights(), total_core_time=3, primal_repair_time_share=.2,
        primal_repair_min_seconds=.5, primal_repair_max_seconds=1,
        mip_gap=0, threads=1, seed=0, root_prepass=False, warm_start=False,
        enable_alns=False, aggregate_recourse_lb=True, analytic_recourse_lb=False)
    assert result["ok"]
    assert result["phase_primal_repair"]["ok"]
    assert result["phase_primal_repair"]["guide_source"] == "bbc_incumbent_support"
    assert result["phase_primal_repair"]["ub_source"] == "checked_monolithic_feasible_solution"
    assert result["core_best"]["feasibility_report"]["feasible"]
    assert result["core_best"]["lb"] <= result["core_best"]["ub"] + 1e-6

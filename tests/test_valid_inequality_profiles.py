import pytest

from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_master import build_master_model


@pytest.mark.gurobi
def test_common_profile_reports_only_registered_families():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    _, _, context = build_master_model(data, Weights(), add_valid_inequalities=True,
                                       valid_inequality_profile="common",
                                       analytic_recourse_lb=False)
    diagnostics = context["master_strengthening"]
    assert diagnostics["valid_inequality_profile"] == "common"
    assert diagnostics["valid_inequality_constraint_count"] == sum(diagnostics["valid_inequality_count_by_family"].values())
    assert set(diagnostics["valid_inequality_count_by_family"]) == {
        "ship_size_period_handling", "minimum_compatible_open_bays", "open_monotonicity"}


@pytest.mark.gurobi
def test_disabled_profile_adds_no_valid_inequalities():
    data = prepare_instance(build_builtin_instance("tiny"))
    _, _, context = build_master_model(data, Weights(), add_valid_inequalities=False,
                                       analytic_recourse_lb=False)
    diagnostics = context["master_strengthening"]
    assert diagnostics["valid_inequality_profile"] == "none"
    assert diagnostics["valid_inequality_constraint_count"] == 0

import pytest

from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_master import build_master_model


def reference_master_point(data):
    model, variables, _ = build_master_model(data, Weights(), relax=True,
                                              add_valid_inequalities=False,
                                              aggregate_recourse_lb=True,
                                              aggregate_relaxation_level="size",
                                              analytic_recourse_lb=False)
    model.optimize()
    return {"x": {k: v.X for k, v in variables["x"].items()},
            "alloc": {k: v.X for k, v in variables["alloc_boxes"].items()}}


def fixed_master_bound(data, level, point):
    model, variables, context = build_master_model(
        data, Weights(), relax=True, add_valid_inequalities=False,
        aggregate_recourse_lb=True, aggregate_relaxation_level=level,
        analytic_recourse_lb=False)
    # Compare at exactly the same master-feasible point.
    for key, value in point["x"].items(): variables["x"][key].LB = variables["x"][key].UB = value
    for key, value in point["alloc"].items(): variables["alloc_boxes"][key].LB = variables["alloc_boxes"][key].UB = value
    model.optimize()
    return variables["eta"].X, context["master_strengthening"]


@pytest.mark.gurobi
def test_pod_size_bound_dominates_size_at_same_master_point():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    point = reference_master_point(data)
    size, size_diag = fixed_master_bound(data, "size", point)
    pod_size, pod_diag = fixed_master_bound(data, "pod_size", point)
    assert pod_size + 1e-6 >= size
    assert size_diag["aggregate_level"] == "size"
    assert pod_diag["aggregate_level"] == "pod_size"
    assert pod_diag["aggregate_variable_count"] > 0 and pod_diag["aggregate_constraint_count"] > 0

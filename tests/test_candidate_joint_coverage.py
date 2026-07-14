from candidate_domain import build_candidate_domain, check_joint_candidate_feasibility
from data import get_data_tiny_benders, prepare_instance
from model_common import ship_groups


def test_joint_coverage_feasible_for_generated_domain():
    data = prepare_instance(get_data_tiny_benders())
    result = build_candidate_domain(data, {"source": "static_fallback", "diagnostics": {}})
    assert result["diagnostics"]["joint_coverage_status"] == "feasible"


def test_jointly_infeasible_overlapping_groups_is_detected():
    data = prepare_instance(get_data_tiny_benders())
    candidates = {}
    for j in data["J_new"]:
        for group in ship_groups(data, j):
            candidates[j, group] = [next(i for i in data["I_list"] if data["Fixed_Bay_Mode"][i] == data["GroupAttrs"][group]["size"])]
    # Remove all residual storage from the chosen bays, while individual group demand remains positive.
    for bays in candidates.values():
        for i in bays:
            data["I"][i]["cap"] = 0.0
    assert check_joint_candidate_feasibility(data, candidates)["status"] == "infeasible"

def test_integer_completion_uses_integer_reserve_rhs():
    data = prepare_instance(get_data_tiny_benders())
    candidates = build_candidate_domain(data, {"source": "static_fallback", "diagnostics": {}})["candidate_bays"]
    result = check_joint_candidate_feasibility(data, candidates, integer_reserve=True)
    assert result["status"] == "feasible" and result["full_start"] is not None

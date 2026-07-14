from candidate_domain import build_candidate_domain
from config import Weights
from data import get_data_tiny_benders, prepare_instance
from solver_aggregate_guide import solve_aggregate_guide
from solver_restricted_repair import solve_restricted_monolithic_repair


def test_repair_incumbent_is_canonicalized_by_oracle():
    data = prepare_instance(get_data_tiny_benders())
    guide = solve_aggregate_guide(data, Weights(), time_limit=1)
    domain = build_candidate_domain(data, guide)
    result = solve_restricted_monolithic_repair(data, Weights(), domain["candidate_bays"], time_limit=3,
                                                guide_result=guide, mip_gap=0)
    assert result["ok"] and result["checker"]["feasible"] and result["canonical_checker"]["feasible"]
    assert result["oracle_status_name"] == "OPTIMAL"
    assert result["canonical_ub"] <= result["repair_objective"] + 1e-5
    assert result["restricted_variable_count"] <= result["estimated_full_variable_count"]

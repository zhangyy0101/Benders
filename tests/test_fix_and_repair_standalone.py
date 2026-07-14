from config import Weights
from data import get_data_tiny_benders, prepare_instance
from solver_fix_and_repair import solve_aggregate_guided_fix_and_repair

def test_standalone_tiny_returns_only_exact_ub_events():
 d=prepare_instance(get_data_tiny_benders());r=solve_aggregate_guided_fix_and_repair(d,Weights(),time_limit=3)
 assert r["ok"] and r["oracle_consistent"] and r["evaluation"]["feasibility"]["feasible"]
 assert r["guide"]["source"] in {"mip_incumbent","lp_fallback","static_fallback"}
 assert next(e for e in r["anytime_trace"] if e["phase"]=="guide")["ub"] is None
 assert all(e["ub"] is not None for e in r["anytime_trace"] if e["phase"] in {"repair","final"})

def test_standalone_zero_budget_is_harmless_failure():
 d=prepare_instance(get_data_tiny_benders());r=solve_aggregate_guided_fix_and_repair(d,Weights(),time_limit=0)
 assert not r["ok"] and r["ub"] is None and r["solution"] is None

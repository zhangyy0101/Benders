"""Regression tests for the Route-B gap-95% follow-up audit."""
import copy
from config import Weights
from data import get_data_tiny_benders, prepare_instance
from model_common import required_reserve
from model_master import build_master_model, extract_master_point
from model_monolithic import build_monolithic_model, extract_solution, evaluate_solution
from model_recourse import GlobalRecourseOracle
from solution_validation import validate_solution
from solver_alns import adaptive_lns

def tiny(): return prepare_instance(get_data_tiny_benders())

def test_aggregate_relaxation_is_not_above_exact_recourse():
    d=tiny();m,v,c=build_master_model(d,Weights(),relax=True);m.Params.OutputFlag=0;m.optimize();p=extract_master_point(v)
    oracle=GlobalRecourseOracle(d,Weights());oracle.update_rhs(p["alloc_boxes"]);oracle.solve()
    assert oracle.model.Status==2;assert c["aggregate"]["aggregate_objective"].getValue()<=oracle.objective_value()+1e-6

def test_aggregate_and_analytic_lbs_strengthen_weak_master():
    d=tiny();weak,_,_=build_master_model(d,Weights(),relax=True,aggregate_recourse_lb=False,analytic_recourse_lb=False);strong,_,_=build_master_model(d,Weights(),relax=True);weak.optimize();strong.optimize()
    assert strong.ObjVal>=weak.ObjVal-1e-7 and strong.ObjVal>weak.ObjVal+1

def test_aggregate_master_preserves_tiny_optimum():
    d=tiny();m,_,_=build_master_model(d,Weights());mono,_,_=build_monolithic_model(d,Weights());m.optimize();mono.optimize();assert m.ObjBound<=mono.ObjVal+1e-6

def test_exact_reserve_integer_and_continuous():
    d=tiny();g=d["G"][0];assert required_reserve(d,"J1",g,0,"integer")==2 and required_reserve(d,"J1",g,0,"continuous")==2.0
    d["Alpha"]=.6;assert required_reserve(d,"J1",g,0,"integer")==2 and required_reserve(d,"J1",g,0,"continuous")==2.0

def test_master_and_monolithic_share_reserve_equalities():
    d=tiny();a,_,_=build_master_model(d,Weights());b,_,_=build_monolithic_model(d,Weights());
    assert len([c for c in a.getConstrs() if c.ConstrName.startswith("reserve_")])==len([c for c in b.getConstrs() if c.ConstrName.startswith("reserve_")])

def test_independent_checker_accepts_exact_solution_and_rejects_mutation():
    d=tiny();m,v,_=build_monolithic_model(d,Weights());m.optimize();s=extract_solution(v);assert validate_solution(d,s)["feasible"]
    bad=copy.deepcopy(s);bad["alloc_boxes"][next(iter(bad["alloc_boxes"]))]+=.5;assert not validate_solution(d,bad)["feasible"]

def test_adaptive_lns_uses_persistent_model_and_tracks_operators():
    d=tiny();m,v,_=build_monolithic_model(d,Weights());m.optimize();s=extract_solution(v);r=adaptive_lns(d,Weights(),s,time_limit=.15,repair_time=.05,seed=3)
    assert r["persistent_repair_model"] and {"random","conflict","distance"}<=set(r["operator_stats"])
    assert all("weight" in x for x in r["operator_stats"].values())

def test_all_public_adapters_pass_strict_inventory_validation():
    from instance_registry import BUILTIN_INSTANCES
    for factory in BUILTIN_INSTANCES.values(): prepare_instance(factory())

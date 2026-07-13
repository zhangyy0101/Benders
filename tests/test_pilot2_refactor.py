import copy
from algorithm_configurations import get_algorithm_configuration
from anytime import canonicalize,trace_metrics
from benchmark_io import load_instance
from config import Weights
from model_common import arrival,ship_group_pairs,ship_groups
from model_master import build_master_model
from pilot_benchmark_suite import RANGES,audit_instance

def test_pilot2_generated_suite_passes_business_audit():
 for size,prefix in (("small","S01"),("medium","M01"),("large","L01")):
  d=load_instance(f"benchmarks/paper_exp_v1_pilot2/{size}/{prefix}.json");assert audit_instance(d,size_class=size)["status"]=="PASS";assert len(d["N"])==12

def test_sparse_helpers_are_backward_compatible_and_inactive_arrival_is_zero():
 d=load_instance("benchmarks/paper_exp_v1_pilot2/small/S01.json");j=d["J_new"][0];inactive=next(g for g in d["G"] if g not in ship_groups(d,j));assert arrival(d,j,inactive,0)==0
 legacy=copy.deepcopy(d);legacy.pop("ActiveGroupsByShip");assert len(ship_group_pairs(legacy))==len(legacy["J_new"])*len(legacy["G"])

def test_sparse_master_reduces_alloc_variables():
 d=load_instance("benchmarks/paper_exp_v1_pilot2/small/S01.json");m,v,_=build_master_model(d,Weights());sparse=len(v["alloc_boxes"]);dense=len(d["I_list"])*len(d["J_new"])*len(d["G"])*len(d["N"]);assert sparse<.8*dense;m.dispose()

def test_c0_c8_hashes_unique_and_required_differences_isolated():
 configs=[get_algorithm_configuration(f"C{i}_{name}") for i,name in enumerate(("bbc_core","core_analytic","core_aggregate","core_both_lb","both_lb_root","both_lb_warm","both_lb_warm_alns","both_lb_root_warm_alns","both_lb_root_warm_alns_valid"))];assert len({c["configuration_hash"] for c in configs})==9
 assert configs[6]["alns"] and not configs[5]["alns"];assert configs[8]["valid_inequalities"] and not configs[7]["valid_inequalities"]

def test_anytime_monotonic_and_metrics():
 t=canonicalize([{"time":2,"ub":10,"lb":2},{"time":1,"ub":12,"lb":1},{"time":3,"ub":11,"lb":4}],4,10,4);assert [p["time"] for p in t]==sorted(p["time"] for p in t);assert [p["ub"] for p in t if p["ub"] is not None]==sorted((p["ub"] for p in t if p["ub"] is not None),reverse=True);assert trace_metrics(t,4,9)["time_to_first_feasible"]==1

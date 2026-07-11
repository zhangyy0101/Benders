import math,random
from data import get_data_tiny_concentration,prepare_instance
from model_monolithic import build_monolithic_model,extract_solution
from config import Weights
from model_common import outbound_pressure
from solver_alns import build_released_variable_keys,build_source_pair_pool,select_destination_pairs,select_source_pairs

def setup():
 d=prepare_instance(get_data_tiny_concentration());m,v,_=build_monolithic_model(d,Weights());m.optimize();return d,extract_solution(v)
def test_pair_count_uses_operator_pool():
 pool=[("i",j) for j in range(4)];assert len(select_source_pairs(pool,.25,random.Random(0)))==1
def test_full_pair_trajectory_counts():
 d,_=setup();rx,ra=build_released_variable_keys(d,[("A20","J1")],set(d["N"]));assert len(rx)==len(d["N"]) and len(ra)==len(d["G"])*len(d["N"])
def test_interval_uses_suffix():
 d,s=setup();rng=random.Random(4);pool,c=build_source_pair_pool(d,s,"interval",rng,outbound_pressure(d));assert c["free_periods"]==set(d["N"][d["N"].index(c["free_period_start"]):])
def test_active_has_feasible_destination():
 d,s=setup();rng=random.Random(0);pool,c=build_source_pair_pool(d,s,"active",rng,outbound_pressure(d));src=select_source_pairs(pool,.25,rng);dst=select_destination_pairs(d,s,src,"active",1,rng,c);assert src and dst and not set(src)&set(dst)
def test_preferred_pairs_are_really_preferred():
 preferred=[("a",1),("b",1)];fallback=[("c",1),("d",1)];assert set(select_source_pairs(preferred+fallback,.5,random.Random(0),preferred_pool=preferred,fallback_pool=fallback))<=set(preferred)
def test_invalid_alns_parameters_raise():
 import pytest
 from solver_alns import adaptive_lns
 d,s=setup()
 for kwargs in ({"repair_time":0},{"min_destroy":.8,"max_destroy":.2},{"destination_ratio":-1},{"stall_iters":0}):
  with pytest.raises(ValueError):adaptive_lns(d,Weights(),s,time_limit=0,**kwargs)

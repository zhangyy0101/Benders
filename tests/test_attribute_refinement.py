from config import Weights
from data import get_data_tiny_route_a,prepare_instance
from model_common import attribute_score,raw_components
from solver_mip_alns import solve_attribute_refinement,solve_core_mip,solve_strengthened_mip_alns

def _ref(scope="final"):
    d=prepare_instance(get_data_tiny_route_a()); core=solve_core_mip(d,Weights(),time_limit_s=3,mip_gap=0); return d,core,solve_attribute_refinement(d,Weights(),core["solution"],core["ub"],epsilon=.01,attribute_scope=scope,time_limit_s=3,mip_gap=0)
def test_refinement_respects_core_cap():
    _d,_c,r=_ref(); assert r["candidate_core_cost"]<=r["core_cap"]+1e-5
def test_all_attribute_metrics_use_same_scope():
    d,c,final=_ref("final"); _d,_c,horizon=_ref("horizon"); assert final["start_attribute_score"]==attribute_score(d,Weights(),raw_components(d,c["solution"],"final")); assert horizon["start_attribute_score"]==attribute_score(d,Weights(),raw_components(d,c["solution"],"horizon"))
def test_refined_solution_not_used_for_core_gap():
    d=prepare_instance(get_data_tiny_route_a()); r=solve_strengthened_mip_alns(d,Weights(),phase1_time=2,lns_time=.1,phase3_time=2,attribute_time=2); assert r["core_best"]["gap"]==0
def test_attribute_score_recomputed_correctly():
    d,c,r=_ref(); assert r["start_attribute_score"]==attribute_score(d,Weights(),raw_components(d,c["solution"],"final"))

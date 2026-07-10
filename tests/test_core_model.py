from gurobipy import GRB
from config import Weights
from data import get_data_3new6old_fixed, prepare_instance
from model_core import build_core_monolithic_model

def test_core_model_contains_complete_flow_variables():
    m,v,e=build_core_monolithic_model(prepare_instance(get_data_3new6old_fixed()),Weights(),alloc_domain="continuous")
    assert all(k in v for k in ("alloc_boxes","x","block_use","din","inv","in_share","in_total","avg","g_bal")); assert all(k in e for k in ("core_objective","open_raw","distance_raw","balance_raw","conflict_raw","attribute_objective","pod_raw","weight_raw","height_raw"))
def test_alloc_domain_and_binary_domains():
    d=prepare_instance(get_data_3new6old_fixed()); _m,v,_e=build_core_monolithic_model(d,Weights(),alloc_domain="continuous")
    assert next(iter(v["alloc_boxes"].values())).VType==GRB.CONTINUOUS; assert next(iter(v["x"].values())).VType==GRB.BINARY; assert next(iter(v["block_use"].values())).VType==GRB.BINARY
def test_handling_constraints_use_rate():
    d=prepare_instance(get_data_3new6old_fixed(),.5); m,_v,_e=build_core_monolithic_model(d,Weights(),alloc_domain="continuous"); assert sum(c.ConstrName.startswith("handling_") for c in m.getConstrs())==len(d["I_list"])*len(d["J_new"])*len(d["N"])
def test_valid_inequalities_can_be_disabled():
    d=prepare_instance(get_data_3new6old_fixed()); m,_,_=build_core_monolithic_model(d,Weights(),alloc_domain="continuous",add_valid_inequalities=False); assert not any(c.ConstrName.startswith("monotone_") for c in m.getConstrs())


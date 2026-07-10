from gurobipy import GRB
from config import Weights
from data import get_data_3new6old_fixed, get_data_tiny_route_a, prepare_instance
from model_core import build_core_monolithic_model, evaluate_core_solution
from solver_mip_alns import solve_core_mip

def _sol(valid=True,domain="integer"):
    return solve_core_mip(prepare_instance(get_data_tiny_route_a()),Weights(),time_limit_s=5,mip_gap=0,alloc_domain=domain,add_valid_inequalities=valid,seed=1)

def test_core_model_contains_complete_flow_variables():
    m,v,e=build_core_monolithic_model(prepare_instance(get_data_3new6old_fixed()),Weights(),alloc_domain="continuous")
    assert all(k in v for k in ("alloc_boxes","x","block_use","din","inv","in_share","in_total","avg","g_bal")); assert all(k in e for k in ("core_objective","open_raw","distance_raw","balance_raw","conflict_raw","attribute_objective","pod_raw","weight_raw","height_raw"))
def test_alloc_domain_and_binary_domains():
    d=prepare_instance(get_data_3new6old_fixed()); _m,v,_e=build_core_monolithic_model(d,Weights(),alloc_domain="continuous")
    assert next(iter(v["alloc_boxes"].values())).VType==GRB.CONTINUOUS; assert next(iter(v["x"].values())).VType==GRB.BINARY; assert next(iter(v["block_use"].values())).VType==GRB.BINARY
def test_handling_constraints_use_rate():
    d=prepare_instance(get_data_3new6old_fixed(),.5); m,_v,_e=build_core_monolithic_model(d,Weights(),alloc_domain="continuous"); assert sum(c.ConstrName.startswith("handling_") for c in m.getConstrs())==len(d["I_list"])*len(d["J_new"])*len(d["N"])
def test_valid_inequalities_can_be_disabled():
    d=prepare_instance(get_data_3new6old_fixed()); m,_,_=build_core_monolithic_model(d,Weights(),alloc_domain="continuous",add_valid_inequalities=False); assert not any(c.ConstrName.startswith(("monotone_x","monotone_block")) for c in m.getConstrs())
def test_core_model_feasible_on_small_instance():
    r=_sol(); assert r["status_name"]=="OPTIMAL" and r["gap"]==0
def test_arrival_conservation():
    d=prepare_instance(get_data_tiny_route_a()); s=_sol()["solution"]
    assert all(abs(sum(s["din"][j,g,i,n] for i in d["I_list"])-d["Arrivals_group_interval"][j,g,n])<1e-7 for j in d["J_new"] for g in d["G"] for n in d["N"])
def test_inventory_balance():
    d=prepare_instance(get_data_tiny_route_a()); s=_sol()["solution"]
    assert all(abs(s["inv"][j,g,i,n]-(s["din"][j,g,i,n]+(s["inv"][j,g,i,n-1] if n else 0)))<1e-7 for j in d["J_new"] for g in d["G"] for i in d["I_list"] for n in d["N"])
def test_storage_capacity():
    d=prepare_instance(get_data_tiny_route_a()); s=_sol()["solution"]; assert all(sum(s["alloc_boxes"][i,j,g,n] for j in d["J_new"] for g in d["G"])<=d["I"][i]["cap"]+1e-7 for i in d["I_list"] for n in d["N"])
def test_handling_capacity():
    d=prepare_instance(get_data_tiny_route_a()); s=_sol()["solution"]; assert all(sum(s["din"][j,g,i,n] for g in d["G"])<=d["Bay_Handling_Rate"][i,n]*d["Intervals"][n]["dur"]*s["x"][i,j,n]+1e-7 for i in d["I_list"] for j in d["J_new"] for n in d["N"])
def test_block_flow_equals_bay_flow():
    d=prepare_instance(get_data_tiny_route_a()); s=_sol()["solution"]; assert all(abs(s["in_share"][j,k,g,n]-sum(s["din"][j,g,i,n] for i in d["Bays_in_Block"][k]))<1e-7 for j in d["J_new"] for k in d["K"] for g in d["G"] for n in d["N"])
def test_l1_balance_value():
    r=_sol(); assert abs(r["components"]["raw"]["real_l1"]-sum(r["solution"]["g_bal"].values()))<1e-7
def test_model_objective_equals_recomputed_objective():
    r=_sol(); assert abs(r["ub"]-r["components"]["total_core_cost"])<=1e-5
def test_lb_not_above_ub():
    r=_sol(); assert r["lb"]<=r["ub"]+1e-5
def test_monotonic_x_only_when_no_new_outbound():
    d=prepare_instance(get_data_tiny_route_a()); d["New_Outbound_Req"]={("Ship_New_1",1):1}; m,_,_=build_core_monolithic_model(d,Weights()); assert not any(c.ConstrName.startswith("monotone_x") for c in m.getConstrs())
def test_monotonic_block_use():
    m,_,_=build_core_monolithic_model(prepare_instance(get_data_tiny_route_a()),Weights()); assert any(c.ConstrName.startswith("monotone_block") for c in m.getConstrs())
def test_valid_inequalities_do_not_change_small_instance_optimum():
    assert abs(_sol(True)["ub"]-_sol(False)["ub"])<1e-7

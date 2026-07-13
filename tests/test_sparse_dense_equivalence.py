import copy,pytest
from config import Weights
from data import get_data_tiny_concentration,prepare_instance
from model_master import build_master_model
from model_monolithic import build_monolithic_model
from model_recourse import GlobalRecourseOracle
from solve_direct_gurobi import solve_direct_gurobi
from solver_true_benders import solve_bbc_phase

def equivalent_pair():
 raw=get_data_tiny_concentration();j=raw["J_new"][0];fake="G20_INACTIVE";raw["G"].append(fake);raw["GroupAttrs"][fake]={"size":20,"pod":"PX","height":"STD","weight_class":"LIGHT"}
 for name,value in (("GroupSize",20),("GroupPOD","PX"),("GroupHeight","STD"),("GroupWeightClass","LIGHT")):raw[name][fake]=value
 for n in raw["N"]:raw["Arrivals_group_interval"][j,fake,n]=0.0
 dense=prepare_instance(copy.deepcopy(raw));sparse_raw=copy.deepcopy(raw);sparse_raw["ActiveGroupsByShip"]={j:[g for g in raw["G"] if g!=fake]};sparse=prepare_instance(sparse_raw);return sparse,dense,fake

def test_inactive_groups_create_no_sparse_variables():
 sparse,dense,fake=equivalent_pair();sm,sv,_=build_monolithic_model(sparse,Weights());dm,dv,_=build_monolithic_model(dense,Weights());assert not any(fake in key for name in ("alloc_boxes","din","inv","in_share") for key in sv[name]);assert len(sv["alloc_boxes"])<len(dv["alloc_boxes"]);so=GlobalRecourseOracle(sparse,Weights());do=GlobalRecourseOracle(dense,Weights());assert so.model.NumVars<do.model.NumVars;sm.dispose();dm.dispose();so.model.dispose();do.model.dispose()

def test_sparse_dense_direct_optimum_equal():
 sparse,dense,_=equivalent_pair();a=solve_direct_gurobi(sparse,Weights(),time_limit=10,mip_gap=0);b=solve_direct_gurobi(dense,Weights(),time_limit=10,mip_gap=0);assert a["status_name"]==b["status_name"]=="OPTIMAL";assert a["ub"]==pytest.approx(b["ub"],abs=1e-6)

def test_sparse_dense_bbc_core_optimum_equal():
 sparse,dense,_=equivalent_pair();kw=dict(time_limit=15,mip_gap=0,warm_start=True,add_valid_inequalities=False,aggregate_recourse_lb=False,analytic_recourse_lb=False);a=solve_bbc_phase(sparse,Weights(),**kw);b=solve_bbc_phase(dense,Weights(),**kw);assert a["ub"]==pytest.approx(b["ub"],abs=1e-6);assert a["lb"]==pytest.approx(b["lb"],abs=1e-6)

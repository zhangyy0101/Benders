import copy
from config import Weights
from data import get_data_tiny_benders,prepare_instance
from model_partial_master import build_partial_master
from solution_validation import validate_solution
from solver_partial_bbc import solve_partial_bbc

def test_weight_dimension_is_removed_during_preparation():
    data=prepare_instance(get_data_tiny_benders())
    assert data["group_taxonomy"]=="pod_size_height"
    assert "GroupWeightClass" not in data
    assert all(set(a)=={"size","pod","height"} for a in data["GroupAttrs"].values())

def test_partial_master_has_no_eta_or_recourse_optimality_variable():
    data=prepare_instance(get_data_tiny_benders());_,variables,_=build_partial_master(data,Weights())
    assert "eta" not in variables and {"block_alloc","block_flow","pod_support","bay_height"}<=set(variables)

def test_partial_bbc_returns_integer_height_feasible_bay_plan():
    data=prepare_instance(get_data_tiny_benders());result=solve_partial_bbc(data,Weights(),time_limit=3,mip_gap=0)
    assert result["ok"] and result["gap"]<1e-8
    assert result["cut_statistics"]["feasibility_checks"]>0
    assert "optimality_cuts" not in result["cut_statistics"]
    assert validate_solution(data,result["solution"])["violations_by_family"]["height_mixing"]==0

def test_validator_rejects_mixed_height_reservations():
    raw=get_data_tiny_benders();raw["G"].append("G20_HIGH");raw["GroupAttrs"]["G20_HIGH"]={"size":20,"pod":"P3","height":"HIGH"};raw["GroupSize"]["G20_HIGH"]=20;raw["GroupPOD"]["G20_HIGH"]="P3";raw["GroupHeight"]["G20_HIGH"]="HIGH"
    for n in raw["N"]:raw["Arrivals_group_interval"]["J1","G20_HIGH",n]=0
    data=prepare_instance(raw);solution=solve_partial_bbc(data,Weights(),time_limit=3,mip_gap=0)["solution"];bad=copy.deepcopy(solution);std=next(g for g in data["G"] if data["GroupSize"][g]==20 and data["GroupHeight"][g]=="STD");high=next(g for g in data["G"] if data["GroupSize"][g]==20 and data["GroupHeight"][g]=="HIGH");i=next(i for i in data["I_list"] if bad["alloc_boxes"].get((i,"J1",std,max(data["N"])),0)>0);bad["alloc_boxes"][i,"J1",high,max(data["N"])]=1
    assert validate_solution(data,bad)["violations_by_family"]["height_mixing"]>0

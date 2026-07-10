import inspect
from config import MasterWeights,Weights
from data import get_data_baptbi_5n_4b_4p,get_data_tiny_concentration,prepare_instance
from model_concentration import concentration_metadata,evaluate_joint_group_concentration,has_joint_attribute_groups
from model_master import build_master_model
from model_monolithic import build_monolithic_model,evaluate_solution,extract_solution
from solve_direct_gurobi import solve_direct_gurobi
from solver_alns import OPERATORS,concentration_destroy_pool
from solver_true_benders import solve_bbc_phase,solve_true_benders_pipeline

def fixture():return prepare_instance(get_data_tiny_concentration())
def allocations(split=False):
    d=fixture();a={};n=max(d["N"])
    for g in d["G"]:a["A"+str(d["GroupSize"][g]),"J1",g,n]=4
    if split:
        g=d["G"][0];a["A20","J1",g,n]=2;a["B20","J1",g,n]=2
    return d,{"alloc_boxes":a}

def test_joint_group_concentration_zero_at_minimum_blocks():
    d,s=allocations();c=evaluate_joint_group_concentration(d,s);assert c["raw_excess_blocks"]==0 and c["used_blocks_total"]==c["minimum_required_blocks_total"]==2
def test_joint_group_concentration_positive_when_extra_block_used():
    d,s=allocations(True);assert evaluate_joint_group_concentration(d,s)["raw_excess_blocks"]==1
def test_tight_big_m_and_minimum_and_scale():
    d=fixture();c=concentration_metadata(d);g=d["G"][0];assert c["big_m"]["J1",g,"A"]==4 and c["minimum_blocks"]["J1",g]==1 and c["scale"]>0
def test_capacity_cover_inequality_exists_and_is_valid():
    d=fixture();m,_,_=build_master_model(d,Weights());assert any(x.ConstrName.startswith("concentration_cover_") for x in m.getConstrs())
def test_evaluator_matches_monolithic_model():
    d=fixture();m,v,e=build_monolithic_model(d,Weights());m.optimize();s=extract_solution(v);q=evaluate_solution(d,Weights(),s);assert abs(e["concentration_objective"].getValue()-q["concentration_cost"])<1e-6 and q["concentration_raw"]==0
def test_master_objective_and_eta_separate_concentration():
    d=fixture();m,_,c=build_master_model(d,Weights());assert "concentration_expression" in c and "concentration" not in c["aggregate"]
def test_tiny_direct_matches_bbc_with_concentration():
    d=fixture();direct=solve_direct_gurobi(d,Weights(),time_limit=4,mip_gap=0);bbc=solve_bbc_phase(d,Weights(),time_limit=4,mip_gap=0);assert abs(direct["ub"]-bbc["ub"])<1e-5 and bbc["lb"]<=bbc["ub"]+1e-6 and bbc["cut_statistics"]["exact_incumbents_submitted"]>0
def test_no_attribute_instance_disables_concentration():
    d=prepare_instance(get_data_baptbi_5n_4b_4p());assert not has_joint_attribute_groups(d);c=evaluate_joint_group_concentration(d,{"alloc_boxes":{}});assert c["status"]=="NOT_APPLICABLE" and c["raw_excess_blocks"] is None
def test_concentration_destroy_is_structured():
    d=fixture();m,v,_=build_monolithic_model(d,Weights());m.optimize();s=extract_solution(v);keys=list(s["x"]);pool=concentration_destroy_pool(d,s,keys);assert "concentration" in OPERATORS and pool and len(pool)<len(keys)
def test_pipeline_has_no_refinement_stage_or_arguments():
    assert "refinement" not in inspect.signature(solve_true_benders_pipeline).parameters;d=fixture();r=solve_true_benders_pipeline(d,Weights(),total_core_time=2);assert "attribute_refinement" not in r
def test_height_mix_variables_do_not_exist():
    d=fixture();m,_,_=build_monolithic_model(d,Weights());assert not any("height_mix" in v.VarName for v in m.getVars())
def test_zero_weight_disables_binaries():
    d=fixture();w=Weights(master=MasterWeights(concentration=0));m,v,_=build_master_model(d,w);assert "concentration_use" not in v

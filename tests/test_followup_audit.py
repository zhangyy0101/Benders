import copy,math,pytest
from config import Weights
from data import get_data_3new6old_fixed,get_data_tiny_route_a,get_data_baptbi_5n_4b_4p,prepare_instance,simulate_old_inventory,validate_instance_units
from experiment_configs import core_budget,experiment_configurations
from model_common import attribute_scales,attribute_score,has_attribute_data,raw_components,required_reserve
from model_core import build_core_monolithic_model,evaluate_core_solution,extract_solution
from run_experiments import run_one
from solution_validation import validate_core_solution
from solver_mip_alns import solve_attribute_refinement,solve_core_mip

def tiny(alpha=1.0):
    d=get_data_tiny_route_a();d["Alpha"]=alpha;return prepare_instance(d)
def solved(domain="integer",valid=True,symmetry=True):return solve_core_mip(tiny(),Weights(),time_limit_s=2,mip_gap=0,alloc_domain=domain,add_valid_inequalities=valid,symmetry_breaking=symmetry,seed=2)
def test_total_allocation_equals_required_reserve_integer():
    d=tiny();s=solved()["solution"];assert all(sum(s["alloc_boxes"][i,j,g,n] for i in d["I_list"])==required_reserve(d,j,g,n,"integer") for j in d["J_new"] for g in d["G"] for n in d["N"])
def test_total_allocation_equals_required_reserve_continuous():
    d=tiny(1.1);r=solve_core_mip(d,Weights(),time_limit_s=2,mip_gap=0,alloc_domain="continuous");assert all(abs(sum(r["solution"]["alloc_boxes"][i,j,g,n] for i in d["I_list"])-required_reserve(d,j,g,n,"continuous"))<1e-7 for j in d["J_new"] for g in d["G"] for n in d["N"])
def test_no_free_over_reservation():test_total_allocation_equals_required_reserve_integer()
def test_integer_required_reserve_uses_ceiling():assert required_reserve(tiny(1.1),"Ship_New_1","G20",0,"integer")==3
def test_attribute_big_m_is_valid_with_alpha_above_one():
    d=tiny(1.1);core=solve_core_mip(d,Weights(),time_limit_s=2,mip_gap=0);ref=solve_attribute_refinement(d,Weights(),core["solution"],core["ub"],time_limit_s=2,mip_gap=0);assert ref["candidate_feasibility_report"]["feasible"]
def test_attribute_helper_matches_inventory_based_raw_metric():
    d=tiny();m,v,e=build_core_monolithic_model(d,Weights(),include_attribute_helpers=True);m.setObjective(e["attribute_objective"]);m.optimize();s=extract_solution(d,v);raw=raw_components(d,s);assert abs(e["pod_raw"].getValue()-raw["pod_spread"])<1e-7 and abs(e["weight_raw"].getValue()-raw["weight_spread"])<1e-7
def test_attribute_objective_equals_recomputed_attribute_score():
    d=tiny();m,v,e=build_core_monolithic_model(d,Weights(),include_attribute_helpers=True);m.setObjective(e["attribute_objective"]);m.optimize();s=extract_solution(d,v);assert abs(m.ObjVal-evaluate_core_solution(d,Weights(),s)["attribute_score"])<1e-5
def test_final_attribute_scales_use_one_period():assert attribute_scales(tiny(),"final")["height_mix"]==4
def test_horizon_attribute_scales_use_all_periods():assert attribute_scales(tiny(),"horizon")["height_mix"]==8
def test_grouped_arrivals_match_size_arrivals():validate_instance_units(tiny())
def test_grouped_arrival_mismatch_is_rejected():
    d=tiny();d["Arrivals_group_interval"]["Ship_New_1","G20",0]+=.1
    with pytest.raises(ValueError):validate_instance_units(d)
def test_missing_model_key_is_rejected():
    d=tiny();del d["Alpha"]
    with pytest.raises(ValueError):validate_instance_units(d)
def test_fixed_inbound_never_overfills_old_inventory():
    d=get_data_3new6old_fixed();key=next(iter(d["Fixed_In_Flow"]));d["Fixed_In_Flow"][key]=1000
    with pytest.raises(ValueError):prepare_instance(d)
def test_old_outbound_cannot_exceed_available_inventory():
    d=get_data_3new6old_fixed();key=next(iter(d["Block_Outbound_Req"]));d["Block_Outbound_Req"][key]=1e6
    with pytest.raises(ValueError):prepare_instance(d)
def test_old_release_policy_is_explicit():assert prepare_instance(get_data_tiny_route_a())["old_outbound_release_policy"]=="proportional"
def test_proportional_release_preserves_block_total():
    d=prepare_instance(get_data_3new6old_fixed(),old_outbound_release_policy="proportional");assert max(simulate_old_inventory(d)["unserved_outbound"].values(),default=0)<=1e-7
def test_conservative_release_never_overstates_free_capacity():
    raw=get_data_3new6old_fixed();p=prepare_instance(raw,old_outbound_release_policy="proportional");c=prepare_instance(raw,old_outbound_release_policy="conservative");po=simulate_old_inventory(p)["occupancy"];co=simulate_old_inventory(c)["occupancy"];assert all(co[k]>=po[k]-1e-7 for k in po)
def test_independent_checker_accepts_known_feasible_solution():assert solved()["feasibility_report"]["feasible"]
def test_independent_checker_rejects_broken_inventory_balance():
    d=tiny();s=copy.deepcopy(solved()["solution"]);s["inv"][next(iter(s["inv"]))]+=1;assert not validate_core_solution(d,s,alloc_domain="integer",add_valid_inequalities=True)["feasible"]
def test_independent_checker_rejects_broken_handling_capacity():
    d=tiny();s=copy.deepcopy(solved()["solution"]);s["din"][next(iter(s["din"]))]+=100;assert not validate_core_solution(d,s,alloc_domain="integer",add_valid_inequalities=True)["feasible"]
def test_independent_checker_rejects_wrong_integer_allocation():
    d=tiny();s=copy.deepcopy(solved()["solution"]);s["alloc_boxes"][next(iter(s["alloc_boxes"]))]+=.5;assert not validate_core_solution(d,s,alloc_domain="integer",add_valid_inequalities=True)["feasible"]
def test_attribute_refinement_skipped_without_attribute_data():
    d=get_data_tiny_route_a();d.pop("G");d.pop("GroupSize");d.pop("GroupAttrs");d.pop("Arrivals_group_interval");d=prepare_instance(d);c=solve_core_mip(d,Weights(),time_limit_s=2,mip_gap=0);r=solve_attribute_refinement(d,Weights(),c["solution"],c["ub"]);assert r["status"]=="NOT_APPLICABLE" and r["start_attribute_score"] is None
def test_zero_attribute_score_is_not_reported_as_perfect_layout():test_attribute_refinement_skipped_without_attribute_data()
def test_public_adapter_without_attributes_is_detected():
    d=prepare_instance(get_data_baptbi_5n_4b_4p());assert not has_attribute_data(d);assert solve_attribute_refinement(d,Weights(),{},0)["status"]=="NOT_APPLICABLE"
def test_root_bound_and_final_bound_are_separate_fields():
    r=solved();assert "root_relaxation_bound" in r and "final_global_bound" in r
def test_experiment_configs_have_equal_core_budget():
    total=10;assert core_budget(total,{"plain":True})["phase1"]==total and abs(sum(core_budget(total,{}).values())-total)<1e-9
def test_plain_and_route_a_use_same_gap_target():
    a=run_one("tiny",0,experiment_configurations()[0],.2,0,1,.01);b=run_one("tiny",0,experiment_configurations()[1],.2,0,1,.01);assert a["core_gap"]==b["core_gap"]==0
def test_duplicate_experiment_configs_removed():
    names=[x["algorithm"] for x in experiment_configurations(True)];assert len(names)==len(set(names))
def test_symmetry_groups_only_contain_identical_bays():
    d=prepare_instance(get_data_3new6old_fixed());_m,_v,e=build_core_monolithic_model(d,Weights(),symmetry_breaking=True);assert e["symmetry_groups"] and all(len({(d["I"][i]["block"],d["Fixed_Bay_Mode"][i],tuple(d["Bay_Handling_Rate"][i,n] for n in d["N"])) for i in group})==1 for group in e["symmetry_groups"])
def test_symmetry_breaking_preserves_tiny_optimum():assert solved(symmetry=True)["ub"]==solved(symmetry=False)["ub"]
def test_canonical_solution_names():assert set(solved()["solution"])=={"alloc_boxes","x","block_use","din","inv","in_share","in_total","avg","g_bal"}
def test_experiment_core_metrics_match_core_best_solution():
    row=run_one("tiny",3,{"algorithm":"check","refine":False},.2,0,1,0);assert row["core_attribute_score"]==3500 and row["core_solution_source"] in {"phase1","alns","phase3"}
def test_experiment_final_metrics_match_selected_final_solution():
    row=run_one("tiny",3,{"algorithm":"check","refine":True},.2,.1,1,0);assert row["final_attribute_score"]==(row["candidate_attribute_score"] if row["refinement_accepted"] else row["core_attribute_score"])
def test_all_operators_present_in_summary():
    from solver_mip_alns import adaptive_lns,OPERATORS
    d=tiny();r=adaptive_lns(d,Weights(),solved(),time_limit_s=.01,min_iters=1);assert set(r["operators"])==set(OPERATORS)
def test_same_seed_produces_same_tiny_instance_solution():assert solved()["solution"]==solved()["solution"]
def test_noncontiguous_periods_rejected():
    d=tiny();d["N"]=[0,2]
    with pytest.raises(ValueError):validate_instance_units(d)

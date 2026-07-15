import copy

from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_monolithic import evaluate_solution
from solution_evaluation import evaluate_common_solution


def tiny_solution():
    data = prepare_instance(build_builtin_instance("tiny"))
    x = {(i, j, n): 0.0 for i in data["I_list"] for j in data["J_new"] for n in data["N"]}
    alloc = {(i, j, g, n): 0.0 for i in data["I_list"] for j in data["J_new"] for g in data["G"] for n in data["N"]}
    din = {(j, g, i, n): 0.0 for j in data["J_new"] for g in data["G"] for i in data["I_list"] for n in data["N"]}
    inv = dict(din)
    share = {(j, k, g, n): 0.0 for j in data["J_new"] for k in data["K"] for g in data["G"] for n in data["N"]}
    groups={data["GroupSize"][g]:g for g in data["G"]}
    for g, bay in ((groups[20], "A20"), (groups[40], "A40")):
        for n in data["N"]:
            x[bay, "J1", n] = 1.0
            alloc[bay, "J1", g, n] = 2.0 * (n + 1)
            din["J1", g, bay, n] = 2.0
            inv["J1", g, bay, n] = 2.0 * (n + 1)
            share["J1", "A", g, n] = 2.0
    total = {(k, n): (4.0 if k == "A" else 0.0) for k in data["K"] for n in data["N"]}
    avg = {n: 2.0 for n in data["N"]}
    bal = {(k, n): 2.0 for k in data["K"] for n in data["N"]}
    return data, {"x": x, "alloc_boxes": alloc, "din": din, "inv": inv, "in_share": share, "in_total": total, "avg": avg, "g_bal": bal}


def test_objective_wrapper_open_distance_and_component_sum():
    data, solution = tiny_solution()
    result = evaluate_common_solution(data, Weights(), solution)
    assert result == evaluate_solution(data, Weights(), solution)
    assert result["open_raw"] == 4.0
    assert result["distance_raw"] == 800.0
    assert result["kpis"]["distance"]["distance_per_arrival_box"] == 100.0
    assert abs(result["core_cost"] - sum(item["weighted"] for item in result["components"].values())) < 1e-9
    assert result["feasibility"]["feasible"]


def test_concentration_and_workload_statistics():
    data, solution = tiny_solution()
    result = evaluate_common_solution(data, Weights(), solution)
    concentration = result["kpis"]["concentration"]
    assert concentration["joint_group_bay_usage_total"] == 2
    assert concentration["mean_bays_per_positive_ship_group"] == 1
    assert concentration["max_bays_per_positive_ship_group"] == 1
    assert concentration["single_bay_ship_group_ratio"] == 1
    workload = result["kpis"]["workload"]
    assert workload["workload_cv_mean_active_periods"] == 1
    assert workload["peak_block_workload"] == 4
    assert workload["peak_to_mean_block_workload_ratio"] == 2


def test_reserved_and_physical_utilization_are_distinct():
    data, solution = tiny_solution()
    changed = copy.deepcopy(solution)
    g=next(g for g in data["G"] if data["GroupSize"][g]==20);changed["alloc_boxes"]["A20", "J1", g, 1] = 5.0
    utilization = evaluate_common_solution(data, Weights(), changed)["kpis"]["utilization"]
    assert utilization["reserved"]["mean"] != utilization["physical"]["mean"]
    assert utilization["reserved"]["minimum_remaining_boxes"] < utilization["physical"]["minimum_remaining_boxes"]


def test_incomplete_solution_cannot_claim_feasibility():
    data, solution = tiny_solution()
    del solution["inv"]
    result = evaluate_common_solution(data, Weights(), solution)
    assert result["metadata"]["evaluation_incomplete"]
    assert not result["feasibility"]["feasible"]
    assert result["kpis"]["utilization"]["physical"] is None


def test_zero_volume_and_zero_workload_guards():
    data, solution = tiny_solution()
    data["Arrivals_interval"] = {key: 0.0 for key in data["Arrivals_interval"]}
    data["Arrivals_group_interval"] = {key: 0.0 for key in data["Arrivals_group_interval"]}
    solution["in_share"] = {key: 0.0 for key in solution["in_share"]}
    solution["in_total"] = {key: 0.0 for key in solution["in_total"]}
    solution["g_bal"] = {key: 0.0 for key in solution["g_bal"]}
    result = evaluate_common_solution(data, Weights(), solution)
    assert result["metadata"]["zero_arrival_guard_used"]
    assert result["kpis"]["distance"]["distance_per_arrival_box"] == 0
    assert result["kpis"]["workload"]["workload_cv_mean_active_periods"] == 0

"""Multi-cycle simulator with distinct forecast, revision, and execution metrics."""
from __future__ import annotations

from external_baselines import (
    LITERATURE_CONFIGURATIONS,
    solve_literature_baseline,
)
from rolling_data import advance_state, initial_simulation_state, optimization_snapshot
from rolling_solver import solve_rolling_snapshot

REVISION_KEYS = (
    "cancellation_quantity",
    "mandatory_reduction",
    "discretionary_cancel",
    "new_bay_count",
    "block_reallocation_quantity",
    "stability_cost",
)


def run_rolling_case(
    case: dict,
    *,
    time_per_cycle: float = 30,
    mip_gap: float = .01,
    threads: int = 1,
    seed: int = 0,
    configuration: str = "full_bottleneck",
    dependency_profile: str = "current",
    baseline_parameter_profile: str = "frozen",
) -> dict:
    """Optimize each rolling cycle under a common online-decision limit."""
    state = initial_simulation_state(case)
    method_state: dict = {}
    cycles: list[dict] = []
    for _ in range(case.get("execution_cycles", case["cycles"])):
        snapshot = optimization_snapshot(case, state)
        if not snapshot["active_ships"]:
            cycle_index = state["cycle"]
            state, execution = advance_state(case, state, {"reservation": {}, "din": {}})
            cycles.append({
                "cycle": cycle_index,
                "skipped": True,
                "active_ships": [],
                "forecast_diagnostics": {},
                "plan_revision_metrics": {},
                "execution_metrics": execution,
            })
            continue
        if configuration in LITERATURE_CONFIGURATIONS:
            result = solve_literature_baseline(
                snapshot,
                time_limit=time_per_cycle,
                seed=seed + state["cycle"],
                configuration=configuration,
                method_state=method_state,
                parameter_profile=baseline_parameter_profile,
            )
            method_state = result.get("method_state", {})
        else:
            result = solve_rolling_snapshot(
                snapshot,
                time_limit=time_per_cycle,
                mip_gap=mip_gap,
                threads=threads,
                seed=seed + state["cycle"],
                configuration=configuration,
                dependency_profile=dependency_profile,
            )
        components = result["solution"]["components"] if result.get("solution") else {}
        forecast = {
            "predicted_shortage": components.get("predicted_shortage"),
            "normalized_operations_score": components.get(
                "normalized_operations_score"
            ),
            "concentration_raw": components.get("concentration_raw"),
            "concentration_normalized": components.get(
                "concentration_normalized"
            ),
            "occupancy_balance_raw": components.get("occupancy_balance_raw"),
            "occupancy_balance_normalized": components.get(
                "occupancy_balance_normalized"
            ),
            "distance_raw": components.get("distance_raw"),
            "distance_normalized": components.get("distance_normalized"),
            "in_out_conflict_raw": components.get("in_out_conflict_raw"),
            "in_out_conflict_normalized": components.get(
                "in_out_conflict_normalized"
            ),
        }
        revision = {key: components.get(key) for key in REVISION_KEYS}
        cycle_row = {
            "cycle": state["cycle"],
            "active_ships": snapshot["active_ships"],
            "new_ships": snapshot["new_ships"],
            "continuing_ships": snapshot["continuing_ships"],
            **{
                key: value
                for key, value in result.items()
                if key not in {"solution", "method_state"}
            },
            "forecast_diagnostics": forecast,
            "plan_revision_metrics": revision,
        }
        if not result["ok"]:
            cycle_row["execution_metrics"] = None
            cycles.append(cycle_row)
            break
        state, execution = advance_state(case, state, result["solution"])
        cycle_row["execution_metrics"] = execution
        cycles.append(cycle_row)

    def total(section: str, key: str) -> float:
        return sum((row.get(section) or {}).get(key, 0) or 0 for row in cycles)

    def mean(section: str, key: str) -> float:
        values = [
            (row.get(section) or {}).get(key)
            for row in cycles
            if (row.get(section) or {}).get(key) is not None
        ]
        return sum(values) / len(values) if values else 0.0

    def maximum(section: str, key: str) -> float:
        values = [
            (row.get(section) or {}).get(key)
            for row in cycles
            if (row.get(section) or {}).get(key) is not None
        ]
        return max(values, default=0.0)

    realized_arrivals = total("execution_metrics", "realized_arrivals")
    realized_unplaced = total("execution_metrics", "realized_unplaced")
    fallback = total("execution_metrics", "fallback_placement_quantity")
    previous_basis = sum(
        (row.get("stability_budget_diagnostics") or {}).get("previous_reservation", 0)
        for row in cycles
    )
    discretionary = total("plan_revision_metrics", "discretionary_cancel")
    total_audit_wall = sum(
        row.get("audit_wall_time", row.get("total_wall_time", 0)) or 0
        for row in cycles
    )
    total_online_decision = sum(
        row.get("online_decision_time", row.get("runtime", 0)) or 0
        for row in cycles
    )
    total_solver = sum(row.get("solver_time", 0) or 0 for row in cycles)
    total_solution_extract = sum(
        row.get("solution_extract_time", 0) or 0 for row in cycles
    )
    total_model_dispose = sum(
        row.get("model_dispose_time", 0) or 0 for row in cycles
    )
    total_final_model_dispose = sum(
        row.get("final_model_dispose_time", 0) or 0 for row in cycles
    )
    total_validation = sum(
        row.get("validation_time", 0) or 0 for row in cycles
    )
    total_preprocessing = sum(
        (row.get("preprocessing_time", 0) or 0)
        + (row.get("model_build_time", 0) or 0)
        + (row.get("bottleneck_selection_time", 0) or 0)
        for row in cycles
    )
    total_bottleneck_selection = sum(
        row.get("bottleneck_selection_time", 0) or 0 for row in cycles
    )
    ship_pod_bay_count_sum = total(
        "execution_metrics", "realized_ship_pod_bay_count_sum"
    )
    ship_pod_observation_count = total(
        "execution_metrics", "realized_ship_pod_observation_count"
    )
    cycle_first = [
        row["cycle_first_incumbent_wall_time"]
        for row in cycles
        if row.get("cycle_first_incumbent_wall_time") is not None
    ]
    final_stage_gaps = [
        row["final_stage_mip_gap"]
        for row in cycles
        if row.get("final_stage_mip_gap") is not None
    ]
    stage_nodes = [
        stage.get("nodes", 0.0)
        for row in cycles
        for stage in row.get("stages", [])
    ]
    termination_statuses = [
        row["termination_status"]
        for row in cycles
        if not row.get("skipped") and row.get("termination_status")
    ]
    if "VALIDATION_FAILED" in termination_statuses:
        termination_status = "VALIDATION_FAILED"
    elif "DEADLINE_MISS" in termination_statuses:
        termination_status = "DEADLINE_MISS"
    elif "TIME_LIMIT_FEASIBLE" in termination_statuses:
        termination_status = "TIME_LIMIT_FEASIBLE"
    else:
        termination_status = "FEASIBLE"
    return {
        "ok": all(row.get("ok", True) for row in cycles),
        "termination_status": termination_status,
        "configuration": configuration,
        "cycles": cycles,
        "final_state": state,
        "total_runtime": total_online_decision,
        "total_online_decision_time": total_online_decision,
        "total_audit_wall_time": total_audit_wall,
        "total_wall_time": total_audit_wall,
        "total_solver_time": total_solver,
        "total_solution_extract_time": total_solution_extract,
        "total_model_dispose_time": total_model_dispose,
        "total_final_model_dispose_time": total_final_model_dispose,
        "total_validation_time": total_validation,
        "total_preprocessing_time": total_preprocessing,
        "total_bottleneck_selection_time": total_bottleneck_selection,
        "total_realized_arrivals": realized_arrivals,
        "total_planned_placement_quantity": total(
            "execution_metrics", "planned_placement_quantity"
        ),
        "total_planned_infeasible_quantity": total(
            "execution_metrics", "planned_infeasible_quantity"
        ),
        "total_fallback_placement_quantity": fallback,
        "total_fallback_candidate_attempts": total(
            "execution_metrics", "fallback_candidate_attempts"
        ),
        "fallback_rate": fallback / realized_arrivals if realized_arrivals else 0.0,
        "total_realized_unplaced": realized_unplaced,
        "unplaced_rate": realized_unplaced / realized_arrivals if realized_arrivals else 0.0,
        "total_realized_distance": total("execution_metrics", "realized_distance"),
        "total_realized_in_out_conflict": total(
            "execution_metrics", "realized_in_out_conflict"
        ),
        "realized_ship_pod_bay_count_sum": ship_pod_bay_count_sum,
        "realized_ship_pod_observation_count": ship_pod_observation_count,
        "mean_realized_bays_per_ship_pod": (
            ship_pod_bay_count_sum / ship_pod_observation_count
            if ship_pod_observation_count else 0.0
        ),
        "max_realized_bays_per_ship_pod": maximum(
            "execution_metrics", "realized_max_bays_per_ship_pod"
        ),
        "total_realized_support_activation_count": total(
            "execution_metrics", "realized_support_activation_count"
        ),
        "max_realized_peak_block_utilization": maximum(
            "execution_metrics", "realized_peak_block_utilization"
        ),
        "mean_realized_utilization_deviation": mean(
            "execution_metrics", "realized_mean_absolute_utilization_deviation"
        ),
        "max_realized_utilization_spread": maximum(
            "execution_metrics", "realized_max_utilization_spread"
        ),
        "total_cancellation_quantity": total(
            "plan_revision_metrics", "cancellation_quantity"
        ),
        "total_mandatory_reduction": total(
            "plan_revision_metrics", "mandatory_reduction"
        ),
        "total_discretionary_cancel": discretionary,
        "total_new_bay_count": total("plan_revision_metrics", "new_bay_count"),
        "total_block_reallocation_quantity": total(
            "plan_revision_metrics", "block_reallocation_quantity"
        ),
        "total_stability_cost": total("plan_revision_metrics", "stability_cost"),
        "previous_reservation_basis": previous_basis,
        "revision_rate": discretionary / previous_basis if previous_basis else 0.0,
        "mean_cycle_first_incumbent_wall_time": (
            sum(cycle_first) / len(cycle_first) if cycle_first else None
        ),
        "max_cycle_first_incumbent_wall_time": max(cycle_first, default=None),
        "mean_final_stage_mip_gap": (
            sum(final_stage_gaps) / len(final_stage_gaps)
            if final_stage_gaps else None
        ),
        "max_final_stage_mip_gap": max(final_stage_gaps, default=None),
        "mean_nodes": sum(stage_nodes) / len(stage_nodes) if stage_nodes else 0.0,
    }

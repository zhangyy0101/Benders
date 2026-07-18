"""Multi-cycle simulator with separate forecast, revision, and execution metrics."""
from __future__ import annotations

from rolling_data import advance_state, initial_simulation_state, optimization_snapshot
from rolling_solver import solve_rolling_snapshot

EXECUTION_KEYS = (
    "realized_arrivals",
    "planned_placement_quantity",
    "fallback_placement_quantity",
    "realized_unplaced",
    "realized_distance",
    "realized_in_out_conflict",
)
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
    configuration: str = "full",
) -> dict:
    state = initial_simulation_state(case)
    cycles = []
    for _ in range(case["cycles"]):
        snapshot = optimization_snapshot(case, state)
        if not snapshot["active_ships"]:
            state, execution = advance_state(case, state, {"reservation": {}, "din": {}})
            cycles.append({
                "cycle": state["cycle"] - 1,
                "skipped": True,
                "active_ships": [],
                "forecast_diagnostics": {},
                "plan_revision_metrics": {},
                "execution_metrics": execution,
            })
            continue
        result = solve_rolling_snapshot(
            snapshot,
            time_limit=time_per_cycle,
            mip_gap=mip_gap,
            threads=threads,
            seed=seed + state["cycle"],
            configuration=configuration,
        )
        components = result["solution"]["components"] if result.get("solution") else {}
        forecast = {
            "predicted_shortage": components.get("predicted_shortage"),
            "predicted_operations_cost": components.get("operations_cost"),
            "predicted_in_out_conflict": components.get("in_out_conflict_raw"),
            "predicted_distance": components.get("distance_raw"),
        }
        revision = {key: components.get(key) for key in REVISION_KEYS}
        cycle_row = {
            "cycle": state["cycle"],
            "active_ships": snapshot["active_ships"],
            "new_ships": snapshot["new_ships"],
            "continuing_ships": snapshot["continuing_ships"],
            **{key: value for key, value in result.items() if key != "solution"},
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

    return {
        "ok": all(row.get("ok", True) for row in cycles),
        "configuration": configuration,
        "cycles": cycles,
        "final_state": state,
        "total_runtime": sum(row.get("runtime", 0) for row in cycles),
        "total_realized_arrivals": total("execution_metrics", "realized_arrivals"),
        "total_planned_placement_quantity": total("execution_metrics", "planned_placement_quantity"),
        "total_fallback_placement_quantity": total("execution_metrics", "fallback_placement_quantity"),
        "total_realized_unplaced": total("execution_metrics", "realized_unplaced"),
        "total_realized_distance": total("execution_metrics", "realized_distance"),
        "total_realized_in_out_conflict": total("execution_metrics", "realized_in_out_conflict"),
        "total_cancellation_quantity": total("plan_revision_metrics", "cancellation_quantity"),
        "total_mandatory_reduction": total("plan_revision_metrics", "mandatory_reduction"),
        "total_discretionary_cancel": total("plan_revision_metrics", "discretionary_cancel"),
        "total_new_bay_count": total("plan_revision_metrics", "new_bay_count"),
        "total_block_reallocation_quantity": total("plan_revision_metrics", "block_reallocation_quantity"),
        "total_stability_cost": total("plan_revision_metrics", "stability_cost"),
    }

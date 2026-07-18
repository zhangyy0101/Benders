"""Controlled rolling experiments with stable, publication-oriented CSV fields."""
from __future__ import annotations

import argparse
import json
import sys

from config import FORECAST_ERROR_MODES
from experiment_metadata import (
    collect_experiment_metadata,
    csv_metadata_fields,
    write_experiment_artifacts,
)
from main import PRESETS
from rolling_data import build_repair_pressure_case, build_synthetic_rolling_case
from rolling_experiment import run_rolling_case
from rolling_solver import CONFIGURATIONS


def stage_summary(result: dict) -> dict:
    stages = [stage for cycle in result["cycles"] for stage in cycle.get("stages", [])]
    first = [
        stage["first_incumbent_time"]
        for stage in stages
        if stage.get("first_incumbent_time") is not None
    ]
    solved_cycles = [cycle for cycle in result["cycles"] if not cycle.get("skipped")]
    return {
        "mean_first_incumbent_time": sum(first) / len(first) if first else None,
        "repair_expansions": sum(
            cycle.get("repair_expansions", 0) for cycle in result["cycles"]
        ),
        "budget_binding_stages": sum(
            bool(stage.get("stability_budget_binding")) for stage in stages
        ),
        "max_variables": max((stage.get("variables", 0) for stage in stages), default=0),
        "max_binary_variables": max(
            (stage.get("binary_variables", 0) for stage in stages),
            default=0,
        ),
        "max_constraints": max(
            (stage.get("constraints", 0) for stage in stages), default=0
        ),
        "final_global_repair_count": sum(
            stage.get("stage") == "global_repair" for stage in stages
        ),
        "mean_preprocessing_time": (
            result["total_preprocessing_time"] / len(solved_cycles)
            if solved_cycles else 0.0
        ),
        "mean_solver_time": (
            result["total_solver_time"] / len(solved_cycles)
            if solved_cycles else 0.0
        ),
    }


def pilot_diagnostics(result: dict) -> dict:
    """Aggregate cycle-level failure, propagation, repair, and polish diagnostics."""
    cycles = [cycle for cycle in result["cycles"] if not cycle.get("skipped")]
    cycle_count = len(cycles)
    failures = [
        cycle["failure_status"]
        for cycle in cycles
        if cycle.get("failure_status")
    ]
    propagated = [
        len((cycle.get("impact_diagnostics") or {}).get("propagated_pairs", []))
        for cycle in cycles
    ]
    pressure = [
        len((cycle.get("impact_diagnostics") or {}).get("pressure_propagation", []))
        for cycle in cycles
    ]
    release = [
        len(
            (cycle.get("impact_diagnostics") or {}).get(
                "release_opportunity_propagation", []
            )
        )
        for cycle in cycles
    ]
    edges = [
        int((cycle.get("impact_diagnostics") or {}).get("dependency_edge_count", 0))
        for cycle in cycles
    ]
    graph_times = [float(cycle.get("dependency_graph_time", 0) or 0) for cycle in cycles]
    expansion_counts = [
        max(
            (
                int(stage.get("dependency_expansion_count", 0) or 0)
                for stage in cycle.get("stages", [])
            ),
            default=propagated[index],
        )
        for index, cycle in enumerate(cycles)
    ]
    global_repairs = sum(
        stage.get("stage") == "global_repair"
        for cycle in cycles
        for stage in cycle.get("stages", [])
    )
    repair_triggered = sum(bool(cycle.get("repair_triggered")) for cycle in cycles)
    polish_triggered = sum(
        bool(cycle.get("quality_polish_triggered")) for cycle in cycles
    )
    polish_improved = sum(
        bool(cycle.get("quality_polish_improved")) for cycle in cycles
    )
    epigraph_slack = [
        float(stage["stability_epigraph_max_slack"])
        for cycle in cycles
        for stage in cycle.get("stages", [])
        if stage.get("stability_epigraph_max_slack") is not None
    ]
    validation_failures = sum(
        cycle.get("validation") is not None
        and not bool(cycle["validation"].get("feasible"))
        for cycle in cycles
    )
    return {
        "failure_status": ";".join(failures) if failures else None,
        "wall_clock_time_limit_exceeded": sum(
            failure == "wall_clock_time_limit_exceeded" for failure in failures
        ),
        "validation_failure_count": validation_failures,
        "no_incumbent_count": sum(failure == "no_incumbent" for failure in failures),
        "preprocessing_time_limit_count": sum(
            failure == "preprocessing_time_limit" for failure in failures
        ),
        "solved_cycle_count": cycle_count,
        "propagation_triggered_count": sum(value > 0 for value in propagated),
        "propagation_trigger_rate": (
            sum(value > 0 for value in propagated) / cycle_count if cycle_count else 0.0
        ),
        "propagated_pair_count": sum(propagated),
        "mean_propagated_pair_count": (
            sum(propagated) / cycle_count if cycle_count else 0.0
        ),
        "dependency_expansion_count": sum(expansion_counts),
        "dependency_edge_count": sum(edges),
        "mean_dependency_edge_count": sum(edges) / cycle_count if cycle_count else 0.0,
        "pressure_propagation_count": sum(pressure),
        "release_opportunity_propagation_count": sum(release),
        "total_dependency_graph_time": sum(graph_times),
        "mean_dependency_graph_time": (
            sum(graph_times) / cycle_count if cycle_count else 0.0
        ),
        "repair_triggered_count": repair_triggered,
        "repair_trigger_rate": repair_triggered / cycle_count if cycle_count else 0.0,
        "global_repair_count": global_repairs,
        "global_repair_rate": global_repairs / cycle_count if cycle_count else 0.0,
        "quality_polish_triggered_count": polish_triggered,
        "quality_polish_trigger_rate": (
            polish_triggered / cycle_count if cycle_count else 0.0
        ),
        "quality_polish_improved_count": polish_improved,
        "quality_polish_improvement_rate": (
            polish_improved / polish_triggered if polish_triggered else 0.0
        ),
        "max_stability_epigraph_slack": max(epigraph_slack, default=None),
    }


def result_row(
    instance: str,
    case: dict,
    configuration: str,
    seed: int,
    time_limit: float,
    result: dict,
    metadata: dict[str, object],
) -> dict:
    predicted_shortage = [
        (cycle.get("forecast_diagnostics") or {}).get("predicted_shortage")
        for cycle in result["cycles"]
    ]
    predicted_shortage = [value for value in predicted_shortage if value is not None]
    predicted_operations = [
        (cycle.get("forecast_diagnostics") or {}).get("predicted_operations_cost")
        for cycle in result["cycles"]
    ]
    predicted_operations = [value for value in predicted_operations if value is not None]
    return {
        "instance": instance,
        "num_blocks": case["num_blocks"],
        "bays_per_block": case["bays_per_block"],
        "num_ships": case["num_ships"],
        "cycles": case["cycles"],
        "initial_utilization": case["requested_initial_utilization"],
        "requested_initial_utilization": case["requested_initial_utilization"],
        "realized_initial_utilization": case["realized_initial_utilization"],
        "forecast_error": case["forecast_error"],
        "forecast_error_mode": case["forecast_error_mode"],
        "outbound_rate": case["nominal_outbound_rate_per_ship_period"],
        "release_delay_periods": case["release_delay_periods"],
        "initial_total_capacity": case["initial_total_capacity"],
        "configuration": configuration,
        "seed": seed,
        "time_limit": time_limit,
        **csv_metadata_fields(metadata),
        "ok": result["ok"],
        "total_wall_time": result["total_wall_time"],
        "total_solver_time": result["total_solver_time"],
        "total_preprocessing_time": result["total_preprocessing_time"],
        **stage_summary(result),
        **pilot_diagnostics(result),
        "realized_arrivals": result["total_realized_arrivals"],
        "planned_placement": result["total_planned_placement_quantity"],
        "planned_infeasible_quantity": result["total_planned_infeasible_quantity"],
        "fallback_placement": result["total_fallback_placement_quantity"],
        "fallback_rate": result["fallback_rate"],
        "realized_unplaced": result["total_realized_unplaced"],
        "unplaced_rate": result["unplaced_rate"],
        "realized_distance": result["total_realized_distance"],
        "realized_in_out_conflict": result["total_realized_in_out_conflict"],
        "mean_realized_bays_per_ship_pod": result["mean_realized_bays_per_ship_pod"],
        "max_realized_bays_per_ship_pod": result["max_realized_bays_per_ship_pod"],
        "realized_support_activation_count": result[
            "total_realized_support_activation_count"
        ],
        "realized_ship_pod_bay_count_sum": result[
            "realized_ship_pod_bay_count_sum"
        ],
        "realized_ship_pod_observation_count": result[
            "realized_ship_pod_observation_count"
        ],
        "max_realized_peak_block_utilization": result[
            "max_realized_peak_block_utilization"
        ],
        "mean_realized_utilization_deviation": result[
            "mean_realized_utilization_deviation"
        ],
        "cancellation_quantity": result["total_cancellation_quantity"],
        "mandatory_reduction": result["total_mandatory_reduction"],
        "discretionary_cancel": result["total_discretionary_cancel"],
        "new_bay_count": result["total_new_bay_count"],
        "block_reallocation_quantity": result["total_block_reallocation_quantity"],
        "stability_cost": result["total_stability_cost"],
        "revision_rate": result["revision_rate"],
        "mean_cycle_first_incumbent_wall_time": result[
            "mean_cycle_first_incumbent_wall_time"
        ],
        "max_cycle_first_incumbent_wall_time": result[
            "max_cycle_first_incumbent_wall_time"
        ],
        "mean_final_stage_mip_gap": result["mean_final_stage_mip_gap"],
        "max_final_stage_mip_gap": result["max_final_stage_mip_gap"],
        "mean_nodes": result["mean_nodes"],
        "mean_cycle_predicted_shortage": (
            sum(predicted_shortage) / len(predicted_shortage)
            if predicted_shortage else None
        ),
        "max_cycle_predicted_shortage": max(predicted_shortage, default=None),
        "mean_cycle_predicted_operations_cost": (
            sum(predicted_operations) / len(predicted_operations)
            if predicted_operations else None
        ),
        "stages": json.dumps(
            [cycle.get("final_stage") for cycle in result["cycles"]]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", choices=PRESETS, default=["small"])
    parser.add_argument("--errors", nargs="+", type=float, default=[.1])
    parser.add_argument(
        "--forecast-error-modes",
        nargs="+",
        choices=FORECAST_ERROR_MODES,
        default=["multiplicative"],
    )
    parser.add_argument(
        "--initial-utilizations",
        nargs="+",
        type=float,
        default=[.25],
    )
    parser.add_argument(
        "--configurations", nargs="+", choices=CONFIGURATIONS, default=["full"]
    )
    parser.add_argument(
        "--pressure-levels", nargs="*", choices=("nearby", "global"), default=[]
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--time", type=float, default=20)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--mip-gap", type=float, default=.01)
    parser.add_argument("--outbound-rate", type=int, default=150)
    parser.add_argument("--release-delay-periods", type=int, default=0)
    parser.add_argument("--containers-per-ship-low", type=int)
    parser.add_argument("--containers-per-ship-high", type=int)
    parser.add_argument("--active-ship-overlap", type=int)
    parser.add_argument("--pod-count", type=int)
    parser.add_argument("--output", default="rolling_results.csv")
    parser.add_argument("--manifest-output")
    args = parser.parse_args()
    metadata = collect_experiment_metadata(
        threads=args.threads,
        mip_gap=args.mip_gap,
        time_limit=args.time,
    )
    rows: list[dict] = []
    for size in args.sizes:
        for error in args.errors:
            for mode in args.forecast_error_modes:
                for utilization in args.initial_utilizations:
                    for seed in args.seeds:
                        for configuration in args.configurations:
                            preset = dict(PRESETS[size])
                            current_low, current_high = preset[
                                "containers_per_ship_range"
                            ]
                            preset["containers_per_ship_range"] = (
                                args.containers_per_ship_low or current_low,
                                args.containers_per_ship_high or current_high,
                            )
                            if args.active_ship_overlap is not None:
                                preset["active_ship_overlap"] = args.active_ship_overlap
                            if args.pod_count is not None:
                                preset["pod_count"] = args.pod_count
                            case = build_synthetic_rolling_case(
                                seed=seed,
                                forecast_error=error,
                                forecast_error_mode=mode,
                                initial_utilization=utilization,
                                nominal_outbound_rate_per_ship_period=(
                                    args.outbound_rate
                                ),
                                release_delay_periods=args.release_delay_periods,
                                **preset,
                            )
                            result = run_rolling_case(
                                case,
                                time_per_cycle=args.time,
                                mip_gap=args.mip_gap,
                                threads=args.threads,
                                seed=seed,
                                configuration=configuration,
                            )
                            row = result_row(
                                size,
                                case,
                                configuration,
                                seed,
                                args.time,
                                result,
                                metadata,
                            )
                            rows.append(row)
                            print(row, flush=True)
    for level in args.pressure_levels:
        for seed in args.seeds:
            case = build_repair_pressure_case(level=level, seed=seed)
            result = run_rolling_case(
                case,
                time_per_cycle=args.time,
                mip_gap=args.mip_gap,
                threads=args.threads,
                seed=seed,
                configuration="full",
            )
            row = result_row(
                f"pressure_{level}",
                case,
                "full",
                seed,
                args.time,
                result,
                metadata,
            )
            rows.append(row)
            print(row, flush=True)
    requested_matrix = {
        "sizes": list(args.sizes),
        "errors": list(args.errors),
        "forecast_error_modes": list(args.forecast_error_modes),
        "initial_utilizations": list(args.initial_utilizations),
        "configurations": list(args.configurations),
        "pressure_levels": list(args.pressure_levels),
        "seeds": list(args.seeds),
        "time_limit": args.time,
        "threads": args.threads,
        "mip_gap": args.mip_gap,
        "outbound_rate": args.outbound_rate,
        "release_delay_periods": args.release_delay_periods,
    }
    write_experiment_artifacts(
        rows=rows,
        output_csv=args.output,
        metadata=metadata,
        requested_matrix=requested_matrix,
        manifest_output=args.manifest_output,
        command=list(sys.argv),
    )
    return 0 if all(row["ok"] for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())

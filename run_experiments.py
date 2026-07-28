"""Controlled rolling experiments with stable, publication-oriented CSV fields."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from config import (
    DEPENDENCY_PROFILES,
    FORECAST_ERROR_MODES,
    FORMAL_SEEDS,
    PREFLIGHT_SEEDS,
)
from external_baselines import (
    CONFIGURATIONS,
    DRA_PARAMETER_PROFILES,
    baseline_row_metadata,
)
from experiment_metadata import (
    collect_experiment_metadata,
    csv_metadata_fields,
    write_experiment_artifacts,
)
from main import PRESETS
from rolling_data import (
    build_oracle_certified_case_family,
    build_repair_pressure_case,
    build_synthetic_rolling_case,
)
from rolling_experiment import run_rolling_case
from rolling_solver import (
    CONFIGURATIONS as CORE_CONFIGURATIONS,
    configuration_features,
)


EXPERIMENT_ID_FIELDS = (
    "instance",
    "num_blocks",
    "bays_per_block",
    "num_ships",
    "cycles",
    "tail_execution_cycles",
    "requested_initial_utilization",
    "ship_volume_factor",
    "oracle_case_class",
    "forecast_error",
    "forecast_error_mode",
    "outbound_rate",
    "release_delay_periods",
    "configuration",
    "baseline_parameter_profile",
    "instance_bundle_sha256",
    "seed",
    "time_limit",
)
NUMERIC_EXPERIMENT_ID_FIELDS = set(EXPERIMENT_ID_FIELDS) - {
    "instance",
    "oracle_case_class",
    "forecast_error_mode",
    "configuration",
    "baseline_parameter_profile",
    "instance_bundle_sha256",
}
EXPERIMENT_ID_DEFAULTS = {
    "tail_execution_cycles": 0,
    "ship_volume_factor": 1.0,
    "oracle_case_class": "not_evaluated",
    "baseline_parameter_profile": "not_applicable",
    "instance_bundle_sha256": "",
}


def _identity_value(field: str, value: object) -> str:
    if field in NUMERIC_EXPERIMENT_ID_FIELDS and value is not None:
        return format(float(value), ".12g")
    return str(value)


def experiment_identity(row: dict) -> tuple[str, ...]:
    """Return a stable identity for one scenario/configuration/seed run."""
    return tuple(
        _identity_value(
            field,
            row.get(field, EXPERIMENT_ID_DEFAULTS.get(field)),
        )
        for field in EXPERIMENT_ID_FIELDS
    )


def planned_experiment_identity(
    instance: str,
    case: dict,
    configuration: str,
    seed: int,
    time_limit: float,
    *,
    baseline_parameter_profile: str = "frozen",
    instance_metadata: dict[str, object] | None = None,
) -> tuple[str, ...]:
    """Build the same identity without solving the experiment."""
    return experiment_identity({
        "instance": instance,
        "num_blocks": case["num_blocks"],
        "bays_per_block": case["bays_per_block"],
        "num_ships": case["num_ships"],
        "cycles": case["cycles"],
        "tail_execution_cycles": case.get("tail_execution_cycles", 0),
        "requested_initial_utilization": case["requested_initial_utilization"],
        "ship_volume_factor": case.get("ship_volume_factor", 1.0),
        "oracle_case_class": case.get("oracle_case_class", "not_evaluated"),
        "forecast_error": case["forecast_error"],
        "forecast_error_mode": case["forecast_error_mode"],
        "outbound_rate": case["nominal_outbound_rate_per_ship_period"],
        "release_delay_periods": case["release_delay_periods"],
        "configuration": configuration,
        "baseline_parameter_profile": (
            baseline_parameter_profile
            if configuration == "dra_rpm" else "not_applicable"
        ),
        "instance_bundle_sha256": (
            (instance_metadata or {}).get("instance_bundle_sha256", "")
        ),
        "seed": seed,
        "time_limit": time_limit,
    })


def _row_ok(row: dict) -> bool:
    value = row.get("ok")
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _resume_rows(
    *,
    output_csv: str,
    manifest_output: str | None,
    metadata: dict[str, object],
    requested_matrix: dict[str, object],
) -> list[dict]:
    """Load a compatible atomic checkpoint or reject an unsafe resume."""
    output_path = Path(output_csv)
    manifest_path = (
        Path(manifest_output)
        if manifest_output is not None
        else output_path.with_suffix(".manifest.json")
    )
    if not output_path.exists() and not manifest_path.exists():
        return []
    if not output_path.exists() or not manifest_path.exists():
        raise ValueError("resume requires both the CSV checkpoint and its manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("metadata") != metadata:
        raise ValueError("resume metadata differs from the current environment or protocol")
    if manifest.get("requested_matrix") != requested_matrix:
        raise ValueError("resume matrix differs from the current requested matrix")
    with output_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if int(manifest.get("row_count", -1)) != len(rows):
        raise ValueError("resume CSV and manifest row counts disagree")
    identities = [experiment_identity(row) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError("resume checkpoint contains duplicate experiment rows")
    return rows


def stage_summary(result: dict) -> dict:
    stages = [stage for cycle in result["cycles"] for stage in cycle.get("stages", [])]
    first = [
        stage["first_incumbent_time"]
        for stage in stages
        if stage.get("first_incumbent_time") is not None
    ]
    solved_cycles = [cycle for cycle in result["cycles"] if not cycle.get("skipped")]
    def cycle_value(cycle: dict, field: str) -> float:
        return float(cycle.get(field, 0) or 0)

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
        "mean_online_decision_time": (
            result["total_online_decision_time"] / len(solved_cycles)
            if solved_cycles else 0.0
        ),
        "mean_solution_extract_time": (
            result["total_solution_extract_time"] / len(solved_cycles)
            if solved_cycles else 0.0
        ),
        "mean_validation_time": (
            result["total_validation_time"] / len(solved_cycles)
            if solved_cycles else 0.0
        ),
        "max_cycle_online_decision_time": max(
            (
                cycle_value(cycle, "online_decision_time")
                for cycle in solved_cycles
            ),
            default=0.0,
        ),
        "max_cycle_audit_wall_time": max(
            (
                cycle_value(cycle, "audit_wall_time")
                for cycle in solved_cycles
            ),
            default=0.0,
        ),
        "max_cycle_solution_extract_time": max(
            (
                cycle_value(cycle, "solution_extract_time")
                for cycle in solved_cycles
            ),
            default=0.0,
        ),
        "max_cycle_validation_time": max(
            (
                cycle_value(cycle, "validation_time")
                for cycle in solved_cycles
            ),
            default=0.0,
        ),
        "max_stage_solver_return_overrun": max(
            (
                float(stage.get("solver_return_overrun", 0) or 0)
                for stage in stages
            ),
            default=0.0,
        ),
        "solver_budget_binding_stages": sum(
            bool(stage.get("solver_budget_binding"))
            for stage in stages
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
    bottleneck_times = [
        float(cycle.get("bottleneck_selection_time", 0) or 0)
        for cycle in cycles
    ]
    bottleneck_triggered = sum(
        bool(cycle.get("bottleneck_repair_triggered")) for cycle in cycles
    )
    adaptive_bypass = sum(
        bool(cycle.get("adaptive_global_bypass")) for cycle in cycles
    )
    aggregate_ladders = [
        cycle.get("aggregate_domain_ladder") or {}
        for cycle in cycles
        if (cycle.get("aggregate_domain_ladder") or {}).get("policy")
        != "disabled"
    ]
    aggregate_domains = [
        ladder.get("selected_domain")
        for ladder in aggregate_ladders
        if ladder.get("selected_domain") is not None
    ]
    aggregate_ladder_times = [
        float(cycle.get("aggregate_domain_ladder_time", 0) or 0)
        for cycle in cycles
    ]
    selected_aggregate_scales = []
    for ladder in aggregate_ladders:
        selected_domain = ladder.get("selected_domain")
        selected_evaluation = next(
            (
                evaluation
                for evaluation in ladder.get("evaluations", [])
                if evaluation.get("domain") == selected_domain
            ),
            None,
        )
        if (
            selected_evaluation is not None
            and selected_evaluation.get("maximum_scale") is not None
        ):
            selected_aggregate_scales.append(
                float(selected_evaluation["maximum_scale"])
            )
    aggregate_safety_fallbacks = sum(
        ladder.get("selection_reason")
        == "global_safety_fallback_without_buffered_domain"
        for ladder in aggregate_ladders
    )
    aggregate_legacy_disagreements = 0
    for cycle in cycles:
        ladder = cycle.get("aggregate_domain_ladder") or {}
        if ladder.get("policy") == "disabled":
            continue
        selected_global = ladder.get("selected_domain") == "Global"
        legacy_global = bool(
            (cycle.get("adaptive_pressure") or {}).get(
                "legacy_route_to_global",
                selected_global,
            )
        )
        aggregate_legacy_disagreements += selected_global != legacy_global
    pressure_ratios = [
        float((cycle.get("adaptive_pressure") or {}).get("pressure_index", 0) or 0)
        for cycle in cycles
        if (cycle.get("adaptive_pressure") or {}).get("pressure_index") is not None
    ]
    peak_load_ratios = [
        float((cycle.get("adaptive_pressure") or {}).get("peak_load_ratio", 0) or 0)
        for cycle in cycles
        if (cycle.get("adaptive_pressure") or {}).get("peak_load_ratio") is not None
    ]
    demand_free_ratios = [
        float(
            (cycle.get("adaptive_pressure") or {}).get(
                "demand_free_capacity_ratio", 0
            )
            or 0
        )
        for cycle in cycles
        if (
            cycle.get("adaptive_pressure") or {}
        ).get("demand_free_capacity_ratio") is not None
    ]
    bottleneck_selected = sum(
        int(cycle.get("bottleneck_selected_pair_block_count", 0) or 0)
        for cycle in cycles
    )
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
    termination_statuses = [
        cycle.get("termination_status")
        for cycle in cycles
        if cycle.get("termination_status")
    ]
    return {
        "failure_status": ";".join(failures) if failures else None,
        "wall_clock_time_limit_exceeded": sum(
            failure in {
                "wall_clock_time_limit_exceeded",
                "online_decision_time_limit_exceeded",
            }
            for failure in failures
        ),
        "online_deadline_miss_count": sum(
            status == "DEADLINE_MISS"
            for status in termination_statuses
        ),
        "time_limit_feasible_count": sum(
            status == "TIME_LIMIT_FEASIBLE"
            for status in termination_statuses
        ),
        "feasible_termination_count": sum(
            status == "FEASIBLE"
            for status in termination_statuses
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
        "adaptive_global_bypass_count": adaptive_bypass,
        "adaptive_global_bypass_rate": (
            adaptive_bypass / cycle_count if cycle_count else 0.0
        ),
        "aggregate_ladder_cycle_count": len(aggregate_ladders),
        "aggregate_ladder_n0_count": aggregate_domains.count("N0"),
        "aggregate_ladder_n1_count": aggregate_domains.count("N1"),
        "aggregate_ladder_n2_count": aggregate_domains.count("N2"),
        "aggregate_ladder_global_count": aggregate_domains.count("Global"),
        "aggregate_ladder_global_rate": (
            aggregate_domains.count("Global") / len(aggregate_domains)
            if aggregate_domains else 0.0
        ),
        "aggregate_ladder_safety_fallback_count": aggregate_safety_fallbacks,
        "aggregate_ladder_legacy_disagreement_count": (
            aggregate_legacy_disagreements
        ),
        "total_aggregate_ladder_time": sum(aggregate_ladder_times),
        "mean_aggregate_ladder_time": (
            sum(aggregate_ladder_times) / cycle_count if cycle_count else 0.0
        ),
        "mean_selected_aggregate_capacity_scale": (
            sum(selected_aggregate_scales) / len(selected_aggregate_scales)
            if selected_aggregate_scales else None
        ),
        "mean_adaptive_pressure_index": (
            sum(pressure_ratios) / len(pressure_ratios)
            if pressure_ratios else 0.0
        ),
        "max_adaptive_pressure_index": max(pressure_ratios, default=0.0),
        "mean_peak_forecast_load_ratio": (
            sum(peak_load_ratios) / len(peak_load_ratios)
            if peak_load_ratios else 0.0
        ),
        "max_peak_forecast_load_ratio": max(peak_load_ratios, default=0.0),
        "mean_demand_free_capacity_ratio": (
            sum(demand_free_ratios) / len(demand_free_ratios)
            if demand_free_ratios else 0.0
        ),
        "max_demand_free_capacity_ratio": max(demand_free_ratios, default=0.0),
        "bottleneck_repair_triggered_count": bottleneck_triggered,
        "bottleneck_repair_trigger_rate": (
            bottleneck_triggered / cycle_count if cycle_count else 0.0
        ),
        "bottleneck_selected_pair_block_count": bottleneck_selected,
        "total_bottleneck_selection_time": sum(bottleneck_times),
        "mean_bottleneck_selection_time": (
            sum(bottleneck_times) / cycle_count if cycle_count else 0.0
        ),
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
    *,
    baseline_parameter_profile: str = "frozen",
    instance_metadata: dict[str, object] | None = None,
) -> dict:
    def forecast_values(field: str) -> list[float]:
        return [
            value
            for cycle in result["cycles"]
            if (
                value := (cycle.get("forecast_diagnostics") or {}).get(field)
            ) is not None
        ]

    def forecast_mean(field: str) -> float | None:
        values = forecast_values(field)
        return sum(values) / len(values) if values else None

    predicted_shortage = forecast_values("predicted_shortage")
    oracle = case.get("oracle_certificate", {})
    oracle_shortage_lower_bound = oracle.get("shortage_lower_bound")
    instance_metadata = instance_metadata or {}
    features = (
        configuration_features(configuration)
        if configuration in CORE_CONFIGURATIONS else {}
    )
    calibration = instance_metadata.get(
        "calibration_scenario_assumptions", {}
    )
    return {
        "instance": instance,
        "instance_id": instance_metadata.get(
            "instance_id", case.get("instance_id", instance)
        ),
        "instance_family": instance_metadata.get(
            "instance_family", case.get("instance_family", "synthetic")
        ),
        "instance_protocol": instance_metadata.get(
            "instance_protocol", case.get("instance_protocol")
        ),
        "instance_bundle_sha256": instance_metadata.get(
            "instance_bundle_sha256", ""
        ) or "",
        "instance_case_sha256": instance_metadata.get(
            "instance_case_sha256"
        ),
        "source_snapshot_sha256": instance_metadata.get(
            "source_snapshot_sha256"
        ),
        "source_raw_snapshot_sha256": instance_metadata.get(
            "source_raw_snapshot_sha256"
        ),
        "source_acquisition_mode": instance_metadata.get(
            "source_acquisition_mode"
        ),
        "source_window_id": instance_metadata.get("source_window_id"),
        "public_panel_role": instance_metadata.get("public_panel_role"),
        "source_publication_ready": instance_metadata.get(
            "source_publication_ready"
        ),
        "calibration_protocol": instance_metadata.get(
            "calibration_protocol"
        ),
        "calibration_scenario_id": instance_metadata.get(
            "calibration_scenario_id"
        ),
        "calibration_capacity_utilization": calibration.get(
            "capacity_utilization"
        ),
        "calibration_export_split": calibration.get(
            "import_export_split_to_export"
        ),
        "calibration_forty_foot_share": calibration.get(
            "forty_foot_box_share"
        ),
        "calibration_high_cube_share": calibration.get(
            "high_cube_share_of_forty"
        ),
        "num_blocks": case["num_blocks"],
        "bays_per_block": case["bays_per_block"],
        "num_ships": case["num_ships"],
        "cycles": case["cycles"],
        "admission_cycles": case.get("admission_cycles", case["cycles"]),
        "tail_execution_cycles": case.get("tail_execution_cycles", 0),
        "execution_cycles": case.get("execution_cycles", case["cycles"]),
        "initial_utilization": case["requested_initial_utilization"],
        "requested_initial_utilization": case["requested_initial_utilization"],
        "realized_initial_utilization": case["realized_initial_utilization"],
        "ship_volume_factor": case.get("ship_volume_factor", 1.0),
        "oracle_case_class": case.get("oracle_case_class", "not_evaluated"),
        "oracle_classification": oracle.get("classification", "not_evaluated"),
        "oracle_minimum_shortage": oracle.get("minimum_shortage"),
        "oracle_incumbent_shortage": oracle.get("incumbent_shortage"),
        "oracle_shortage_lower_bound": oracle_shortage_lower_bound,
        "oracle_zero_shortage_certificate": oracle.get(
            "zero_shortage_certificate"
        ),
        "oracle_positive_shortage_certificate": oracle.get(
            "positive_shortage_certificate"
        ),
        "oracle_proved_optimal": oracle.get("proved_optimal"),
        "oracle_runtime_seconds": oracle.get("runtime_seconds"),
        "oracle_total_demand": oracle.get("total_demand"),
        "forecast_error": case["forecast_error"],
        "forecast_error_mode": case["forecast_error_mode"],
        "outbound_rate": case["nominal_outbound_rate_per_ship_period"],
        "release_delay_periods": case["release_delay_periods"],
        "initial_total_capacity": case["initial_total_capacity"],
        "configuration": configuration,
        "configuration_features": json.dumps(
            features, sort_keys=True, separators=(",", ":")
        ),
        **baseline_row_metadata(configuration, baseline_parameter_profile),
        "seed": seed,
        "time_limit": time_limit,
        **csv_metadata_fields(metadata),
        "ok": result["ok"],
        "termination_status": result["termination_status"],
        "total_online_decision_time": result[
            "total_online_decision_time"
        ],
        "total_audit_wall_time": result["total_audit_wall_time"],
        "total_wall_time": result["total_wall_time"],
        "total_solver_time": result["total_solver_time"],
        "total_solution_extract_time": result[
            "total_solution_extract_time"
        ],
        "total_model_dispose_time": result[
            "total_model_dispose_time"
        ],
        "total_final_model_dispose_time": result[
            "total_final_model_dispose_time"
        ],
        "total_validation_time": result["total_validation_time"],
        "total_preprocessing_time": result["total_preprocessing_time"],
        **stage_summary(result),
        **pilot_diagnostics(result),
        "realized_arrivals": result["total_realized_arrivals"],
        "planned_placement": result["total_planned_placement_quantity"],
        "planned_infeasible_quantity": result["total_planned_infeasible_quantity"],
        "fallback_placement": result["total_fallback_placement_quantity"],
        "fallback_rate": result["fallback_rate"],
        "physical_recovery_placement": result[
            "total_physical_recovery_placement_quantity"
        ],
        "physical_recovery_displaced_reservation": result[
            "total_physical_recovery_displaced_reservation"
        ],
        "pre_physical_recovery_unplaced": result[
            "total_pre_physical_recovery_unplaced"
        ],
        "realized_unplaced": result["total_realized_unplaced"],
        "unplaced_rate": result["unplaced_rate"],
        "realized_arrival_coverage_of_oracle_demand": (
            result["total_realized_arrivals"] / oracle["total_demand"]
            if oracle.get("total_demand")
            else None
        ),
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
        "mean_cycle_normalized_operations_score": forecast_mean(
            "normalized_operations_score"
        ),
        "mean_cycle_predicted_concentration_raw": forecast_mean(
            "concentration_raw"
        ),
        "mean_cycle_predicted_concentration_normalized": forecast_mean(
            "concentration_normalized"
        ),
        "mean_cycle_predicted_occupancy_balance_raw": forecast_mean(
            "occupancy_balance_raw"
        ),
        "mean_cycle_predicted_occupancy_balance_normalized": forecast_mean(
            "occupancy_balance_normalized"
        ),
        "mean_cycle_predicted_distance_raw": forecast_mean("distance_raw"),
        "mean_cycle_predicted_distance_normalized": forecast_mean(
            "distance_normalized"
        ),
        "mean_cycle_predicted_in_out_conflict_raw": forecast_mean(
            "in_out_conflict_raw"
        ),
        "mean_cycle_predicted_in_out_conflict_normalized": forecast_mean(
            "in_out_conflict_normalized"
        ),
        "stages": json.dumps(
            [cycle.get("final_stage") for cycle in result["cycles"]]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="*", choices=PRESETS, default=["small"])
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
        "--configurations",
        nargs="+",
        choices=CONFIGURATIONS,
        default=["full_bottleneck"],
    )
    parser.add_argument(
        "--baseline-parameter-profile",
        choices=DRA_PARAMETER_PROFILES,
        default="frozen",
        help="DRA-RPM profile; ignored by all other configurations",
    )
    parser.add_argument(
        "--pressure-levels", nargs="*", choices=("nearby", "global"), default=[]
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument(
        "--experiment-phase",
        choices=("development", "preflight", "formal"),
        default="development",
        help="record and enforce the seed/cleanliness policy for this batch",
    )
    parser.add_argument(
        "--require-clean-git",
        action="store_true",
        help="reject the batch unless it runs from a clean Git commit",
    )
    parser.add_argument("--time", type=float, default=20)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--mip-gap", type=float, default=.01)
    parser.add_argument(
        "--dependency-profile",
        choices=DEPENDENCY_PROFILES,
        default="current",
    )
    parser.add_argument("--outbound-rate", type=int, default=150)
    parser.add_argument("--release-delay-periods", type=int, default=0)
    parser.add_argument("--containers-per-ship-low", type=int)
    parser.add_argument("--containers-per-ship-high", type=int)
    parser.add_argument("--active-ship-overlap", type=int)
    parser.add_argument("--pod-count", type=int)
    parser.add_argument(
        "--oracle-case-classes",
        nargs="*",
        choices=("feasible", "tight", "overloaded"),
        default=[],
        help=(
            "replace each ordinary synthetic case with selected members of an "
            "offline full-horizon-oracle-certified volume family"
        ),
    )
    parser.add_argument(
        "--oracle-factor-bounds",
        nargs=2,
        type=float,
        default=(.25, 4.0),
        metavar=("LOW", "HIGH"),
    )
    parser.add_argument("--oracle-search-iterations", type=int, default=8)
    parser.add_argument("--oracle-time", type=float, default=60.0)
    parser.add_argument(
        "--output",
        default="local_results/runs/rolling_results.csv",
    )
    parser.add_argument("--manifest-output")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume a compatible row-level checkpoint",
    )
    args = parser.parse_args()
    metadata = collect_experiment_metadata(
        threads=args.threads,
        mip_gap=args.mip_gap,
        time_limit=args.time,
        dependency_profile=args.dependency_profile,
        experiment_phase=args.experiment_phase,
    )
    allowed_phase_seeds = {
        "preflight": set(PREFLIGHT_SEEDS),
        "formal": set(FORMAL_SEEDS),
    }
    if args.experiment_phase in allowed_phase_seeds:
        unexpected = sorted(
            set(args.seeds) - allowed_phase_seeds[args.experiment_phase]
        )
        if unexpected:
            parser.error(
                f"{args.experiment_phase} seeds must come from "
                f"{sorted(allowed_phase_seeds[args.experiment_phase])}; "
                f"unexpected={unexpected}"
            )
    require_clean_git = args.require_clean_git or args.experiment_phase == "formal"
    if require_clean_git and metadata.get("git_dirty") is not False:
        parser.error(
            "a clean, identifiable Git commit is required for this experiment batch"
        )
    requested_matrix = {
        "sizes": list(args.sizes),
        "errors": list(args.errors),
        "forecast_error_modes": list(args.forecast_error_modes),
        "initial_utilizations": list(args.initial_utilizations),
        "configurations": list(args.configurations),
        "baseline_parameter_profile": args.baseline_parameter_profile,
        "pressure_levels": list(args.pressure_levels),
        "seeds": list(args.seeds),
        "experiment_phase": args.experiment_phase,
        "require_clean_git": require_clean_git,
        "time_limit": args.time,
        "threads": args.threads,
        "mip_gap": args.mip_gap,
        "dependency_profile": args.dependency_profile,
        "outbound_rate": args.outbound_rate,
        "release_delay_periods": args.release_delay_periods,
        "containers_per_ship_low": args.containers_per_ship_low,
        "containers_per_ship_high": args.containers_per_ship_high,
        "active_ship_overlap": args.active_ship_overlap,
        "pod_count": args.pod_count,
        "oracle_case_classes": list(args.oracle_case_classes),
        "oracle_factor_bounds": list(args.oracle_factor_bounds),
        "oracle_search_iterations": args.oracle_search_iterations,
        "oracle_time_limit": args.oracle_time,
    }
    case_class_count = max(1, len(args.oracle_case_classes))
    expected_row_count = (
        len(args.sizes)
        * len(args.errors)
        * len(args.forecast_error_modes)
        * len(args.initial_utilizations)
        * len(args.seeds)
        * len(args.configurations)
        * case_class_count
        + len(args.pressure_levels) * len(args.seeds) * len(args.configurations)
    )
    rows: list[dict] = (
        _resume_rows(
            output_csv=args.output,
            manifest_output=args.manifest_output,
            metadata=metadata,
            requested_matrix=requested_matrix,
        )
        if args.resume else []
    )
    completed = {experiment_identity(row) for row in rows}

    def checkpoint(row: dict) -> None:
        identity = experiment_identity(row)
        if identity in completed:
            raise ValueError(f"duplicate experiment row: {identity}")
        rows.append(row)
        completed.add(identity)
        write_experiment_artifacts(
            rows=rows,
            output_csv=args.output,
            metadata=metadata,
            requested_matrix=requested_matrix,
            manifest_output=args.manifest_output,
            command=list(sys.argv),
            expected_row_count=expected_row_count,
        )
        print(row, flush=True)

    for size in args.sizes:
        for error in args.errors:
            for mode in args.forecast_error_modes:
                for utilization in args.initial_utilizations:
                    for seed in args.seeds:
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
                        case_kwargs = {
                            "seed": seed,
                            "forecast_error": error,
                            "forecast_error_mode": mode,
                            "initial_utilization": utilization,
                            "nominal_outbound_rate_per_ship_period": (
                                args.outbound_rate
                            ),
                            "release_delay_periods": args.release_delay_periods,
                            **preset,
                        }
                        if args.oracle_case_classes:
                            family = build_oracle_certified_case_family(
                                factor_bounds=tuple(args.oracle_factor_bounds),
                                search_iterations=args.oracle_search_iterations,
                                oracle_time_limit=args.oracle_time,
                                oracle_threads=args.threads,
                                oracle_seed=seed,
                                **case_kwargs,
                            )
                            cases = [
                                (f"{size}_{label}", family[label])
                                for label in args.oracle_case_classes
                            ]
                        else:
                            case = build_synthetic_rolling_case(
                                **case_kwargs,
                            )
                            cases = [(size, case)]
                        for instance_name, case in cases:
                            for configuration in args.configurations:
                                identity = planned_experiment_identity(
                                    instance_name,
                                    case,
                                    configuration,
                                    seed,
                                    args.time,
                                    baseline_parameter_profile=(
                                        args.baseline_parameter_profile
                                    ),
                                )
                                if identity in completed:
                                    print(
                                        f"resume: skipping {identity}",
                                        flush=True,
                                    )
                                    continue
                                result = run_rolling_case(
                                    case,
                                    time_per_cycle=args.time,
                                    mip_gap=args.mip_gap,
                                    threads=args.threads,
                                    seed=seed,
                                    configuration=configuration,
                                    dependency_profile=args.dependency_profile,
                                    baseline_parameter_profile=(
                                        args.baseline_parameter_profile
                                    ),
                                )
                                row = result_row(
                                    instance_name,
                                    case,
                                    configuration,
                                    seed,
                                    args.time,
                                    result,
                                    metadata,
                                    baseline_parameter_profile=(
                                        args.baseline_parameter_profile
                                    ),
                                )
                                checkpoint(row)
    for level in args.pressure_levels:
        for seed in args.seeds:
            for configuration in args.configurations:
                case = build_repair_pressure_case(level=level, seed=seed)
                identity = planned_experiment_identity(
                    f"pressure_{level}",
                    case,
                    configuration,
                    seed,
                    args.time,
                    baseline_parameter_profile=args.baseline_parameter_profile,
                )
                if identity in completed:
                    print(f"resume: skipping {identity}", flush=True)
                    continue
                result = run_rolling_case(
                    case,
                    time_per_cycle=args.time,
                    mip_gap=args.mip_gap,
                    threads=args.threads,
                    seed=seed,
                    configuration=configuration,
                    dependency_profile=args.dependency_profile,
                    baseline_parameter_profile=args.baseline_parameter_profile,
                )
                row = result_row(
                    f"pressure_{level}",
                    case,
                    configuration,
                    seed,
                    args.time,
                    result,
                    metadata,
                    baseline_parameter_profile=args.baseline_parameter_profile,
                )
                checkpoint(row)
    write_experiment_artifacts(
        rows=rows,
        output_csv=args.output,
        metadata=metadata,
        requested_matrix=requested_matrix,
        manifest_output=args.manifest_output,
        command=list(sys.argv),
        expected_row_count=expected_row_count,
    )
    return 0 if all(_row_ok(row) for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())

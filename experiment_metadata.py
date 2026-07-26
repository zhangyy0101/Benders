"""Reproducible environment metadata and experiment artifact writing."""
from __future__ import annotations

import csv
import json
import os
import platform as platform_module
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import config
from external_baselines import literature_baseline_metadata

try:
    import gurobipy as gp
except ImportError:  # pragma: no cover - the project normally requires Gurobi
    gp = None


def collect_git_metadata(*, timeout: float = 2.0) -> dict[str, object]:
    """Read the current repository identity without making experiments fragile."""
    commands = (
        ("git_commit", ["git", "rev-parse", "HEAD"]),
        ("git_branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        ("git_status", ["git", "status", "--porcelain"]),
    )
    values: dict[str, str] = {}
    try:
        for key, command in commands:
            result = subprocess.run(
                command,
                cwd=Path(__file__).resolve().parent,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                raise OSError(result.stderr.strip() or "Git command failed")
            values[key] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_branch": None, "git_dirty": None}
    return {
        "git_commit": values["git_commit"] or None,
        "git_branch": values["git_branch"] or None,
        "git_dirty": bool(values["git_status"]),
    }


def collect_gurobi_version() -> str | None:
    """Return the installed official Gurobi Python interface version, if readable."""
    try:
        version = gp.gurobi.version() if gp is not None else None
        if not version:
            return None
        return ".".join(str(component) for component in version)
    except Exception:
        return None


def collect_weight_profile(
    dependency_profile: str = "current",
) -> dict[str, dict[str, object]]:
    """Collect algorithm weights and thresholds directly from configuration."""
    dependency_thresholds = config.DEPENDENCY_PROFILES[dependency_profile]
    return {
        "stability": {
            "cancel": config.STABILITY_CANCEL_WEIGHT,
            "new_bay": config.STABILITY_NEW_BAY_WEIGHT,
            "block_reallocation": config.STABILITY_BLOCK_REALLOCATION_WEIGHT,
            "base_ratio": config.STABILITY_BASE_RATIO,
            "change_ratio": config.STABILITY_CHANGE_RATIO,
        },
        "operations": {
            "normalization": config.OPERATION_OBJECTIVE_NORMALIZATION,
            "concentration": config.OPERATION_WEIGHT_CONCENTRATION,
            "balance": config.OPERATION_WEIGHT_BALANCE,
            "distance": config.OPERATION_WEIGHT_DISTANCE,
            "in_out_conflict": config.OPERATION_WEIGHT_IN_OUT_CONFLICT,
        },
        "dependency": {
            "enabled": config.DEPENDENCY_PROPAGATION_ENABLED,
            "trigger_mode": config.DEPENDENCY_TRIGGER_MODE,
            "candidate_overlap": config.DEPENDENCY_WEIGHT_CANDIDATE_OVERLAP,
            "temporal_overlap": config.DEPENDENCY_WEIGHT_TEMPORAL_OVERLAP,
            "capacity_pressure": config.DEPENDENCY_WEIGHT_CAPACITY_PRESSURE,
            "historical_overlap": config.DEPENDENCY_WEIGHT_HISTORICAL_OVERLAP,
            "profile": dependency_profile,
            "edge_threshold": dependency_thresholds["edge_threshold"],
            "path_threshold": dependency_thresholds["path_threshold"],
            "max_depth": config.DEPENDENCY_MAX_DEPTH,
            "decay": config.DEPENDENCY_DECAY,
            "candidate_block_ratio": config.DEPENDENCY_CANDIDATE_BLOCK_RATIO,
            "max_neighbors_per_pair": config.DEPENDENCY_MAX_NEIGHBORS_PER_PAIR,
        },
        "impact_score": {
            "direct_change_threshold": config.DEFAULT_IMPACT_THRESHOLD,
            "adaptive_block_batch_ratio": config.ADAPTIVE_BLOCK_BATCH_RATIO,
            "capacity": config.IMPACT_SCORE_CAPACITY_WEIGHT,
            "distance": config.IMPACT_SCORE_DISTANCE_WEIGHT,
            "outbound": config.IMPACT_SCORE_OUTBOUND_WEIGHT,
            "balance": config.IMPACT_SCORE_BALANCE_WEIGHT,
            "bay": config.IMPACT_SCORE_BAY_WEIGHT,
            "stability": config.IMPACT_SCORE_STABILITY_WEIGHT,
            "time_capacity": config.TIME_CAPACITY_WEIGHT,
            "minimum_period_capacity": config.MINIMUM_PERIOD_CAPACITY_WEIGHT,
        },
        "bottleneck_repair": {
            "selector": "granularity_guarded_minimum_pair_block_cover",
            "budget_ratio": config.BOTTLENECK_SELECTOR_BUDGET_RATIO,
            "max_seconds": config.BOTTLENECK_SELECTOR_MAX_SECONDS,
            "packing_granularity_guard": "one_compatible_bay",
            "fallback": "global_repair",
        },
        "adaptive_controller": {
            "enabled": config.ADAPTIVE_GLOBAL_BYPASS_ENABLED,
            "policy": (
                "buffered_aggregate_lp_domain_ladder"
                if config.AGGREGATE_DOMAIN_LADDER_ENABLED
                else "joint_peak_load_and_demand_free_capacity"
            ),
            "peak_load_threshold": config.ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD,
            "demand_free_capacity_threshold": (
                config.ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD
            ),
            "legacy_pressure_rule_used_for_decision": (
                not config.AGGREGATE_DOMAIN_LADDER_ENABLED
            ),
            "instance_size_label_used": False,
            "high_pressure_route": "global_core_with_common_mip_start",
            "ordinary_route": "bottleneck_guided_progressive_repair",
            "incumbent_guard": (
                "predicted_shortage_then_stability_then_normalized_operations"
            ),
        },
        "aggregate_domain_ladder": {
            "enabled": config.AGGREGATE_DOMAIN_LADDER_ENABLED,
            "levels": list(config.AGGREGATE_DOMAIN_LADDER_LEVELS),
            "budget_ratio": config.AGGREGATE_DOMAIN_LADDER_BUDGET_RATIO,
            "max_seconds": config.AGGREGATE_DOMAIN_LADDER_MAX_SECONDS,
            "forecast_error_buffer_multiplier": (
                config.AGGREGATE_DOMAIN_LADDER_BUFFER_MULTIPLIER
            ),
            "uncertainty_buffer_basis": (
                "declared_error_times_max_visible_forecast_lead_sigma"
            ),
            "screen": "block_size_height_time_capacity_relaxation",
            "selection": (
                "smallest_screened_recovery_level; local levels enter "
                "incumbent-triggered minimum bottleneck repair"
            ),
            "safety_fallback": "global_domain",
            "exact_feasibility_guard": (
                "downstream_integer_mip_and_independent_validation"
            ),
        },
        "quality_polish": {
            "enabled": config.QUALITY_POLISH_ENABLED,
            "pair_ratio": config.QUALITY_POLISH_PAIR_RATIO,
            "blocks_per_pair": config.QUALITY_POLISH_BLOCKS_PER_PAIR,
            "support": config.QUALITY_POLISH_WEIGHT_SUPPORT,
            "distance": config.QUALITY_POLISH_WEIGHT_DISTANCE,
            "overlap": config.QUALITY_POLISH_WEIGHT_OVERLAP,
            "utilization": config.QUALITY_POLISH_WEIGHT_UTILIZATION,
        },
        "runtime": {
            "protocol": config.ONLINE_RUNTIME_PROTOCOL,
            "primary_metric": "online_decision_time",
            "audit_metric": "audit_wall_time",
            "wall_time_tolerance_seconds": config.WALL_TIME_TOLERANCE_SECONDS,
            "postprocessing_reserve_ratio": config.POSTPROCESSING_RESERVE_RATIO,
            "postprocessing_reserve_min_seconds": (
                config.POSTPROCESSING_RESERVE_MIN_SECONDS
            ),
            "postprocessing_reserve_max_seconds": (
                config.POSTPROCESSING_RESERVE_MAX_SECONDS
            ),
            "solver_return_guard_ratio": (
                config.SOLVER_RETURN_GUARD_RATIO
            ),
            "solver_return_guard_min_seconds": (
                config.SOLVER_RETURN_GUARD_MIN_SECONDS
            ),
            "solver_return_guard_max_seconds": (
                config.SOLVER_RETURN_GUARD_MAX_SECONDS
            ),
        },
    }


def collect_experiment_metadata(
    *,
    threads: int,
    mip_gap: float,
    time_limit: float,
    dependency_profile: str = "current",
    experiment_phase: str = "development",
) -> dict[str, object]:
    """Collect one immutable metadata record for an experiment batch."""
    return {
        **collect_git_metadata(),
        "problem_protocol": config.PROBLEM_PROTOCOL,
        "algorithm_version": config.ALGORITHM_VERSION,
        "result_schema_version": config.RESULT_SCHEMA_VERSION,
        "online_runtime_protocol": config.ONLINE_RUNTIME_PROTOCOL,
        "formal_core_configuration": config.FORMAL_CORE_CONFIGURATION,
        "external_baseline_protocol": config.EXTERNAL_BASELINE_PROTOCOL,
        "preprocessing_implementation": (
            config.PREPROCESSING_IMPLEMENTATION
        ),
        "packing_oracle_protocol": config.PACKING_ORACLE_PROTOCOL,
        "formal_seed_set": list(config.FORMAL_SEEDS),
        "formal_primary_configurations": list(
            config.FORMAL_PRIMARY_CONFIGURATIONS
        ),
        "formal_time_budgets_seconds": config.FORMAL_TIME_BUDGETS_SECONDS,
        "formal_public_windows": config.FORMAL_PUBLIC_WINDOWS,
        "external_baselines": literature_baseline_metadata(),
        "experiment_phase": experiment_phase,
        "python_version": platform_module.python_version(),
        "python_implementation": platform_module.python_implementation(),
        "platform": platform_module.platform(),
        "gurobi_version": collect_gurobi_version(),
        "threads": int(threads),
        "mip_gap": float(mip_gap),
        "time_limit": float(time_limit),
        "dependency_profile": dependency_profile,
        "stability_formulation": (
            "exact_big_m"
            if config.USE_EXACT_STABILITY_BIG_M
            else "epigraph_only"
        ),
        "temporal_protocol": {
            "rolling_cycle_hours": config.ROLLING_CYCLE_HOURS,
            "receiving_window_hours": config.RECEIVING_WINDOW_HOURS,
            "time_bucket_hours": config.TIME_BUCKET_HOURS,
            "lookahead_hours": config.LOOKAHEAD_HOURS,
            "admission_lead_band_hours": list(config.ADMISSION_LEAD_BAND_HOURS),
        },
        "validation_profile": {
            "validate_each_execution_period": (
                config.VALIDATE_EACH_EXECUTION_PERIOD
            ),
            "integer_solver_values_normalized_before_validation": True,
            "online_time_start": "before_method_specific_preprocessing",
            "online_time_end": "complete_executable_allocation_available",
            "online_time_includes": [
                "preprocessing",
                "domain_selection",
                "model_build",
                "optimization",
                "callbacks",
                "repair_control",
                "solution_extraction",
            ],
            "online_time_excludes": [
                "independent_validation",
                "final_model_disposal",
                "artifact_serialization",
            ],
            "wall_time_tolerance_seconds": (
                config.WALL_TIME_TOLERANCE_SECONDS
            ),
        },
        "weight_profile": collect_weight_profile(dependency_profile),
    }


def csv_metadata_fields(metadata: dict[str, object]) -> dict[str, object]:
    """Convert shared batch metadata to stable scalar CSV fields."""
    return {
        "git_commit": metadata.get("git_commit"),
        "git_branch": metadata.get("git_branch"),
        "git_dirty": metadata.get("git_dirty"),
        "problem_protocol": metadata.get("problem_protocol"),
        "algorithm_version": metadata.get("algorithm_version"),
        "result_schema_version": metadata.get("result_schema_version"),
        "online_runtime_protocol": metadata.get("online_runtime_protocol"),
        "formal_core_configuration": metadata.get("formal_core_configuration"),
        "external_baseline_protocol": metadata.get(
            "external_baseline_protocol"
        ),
        "preprocessing_implementation": metadata.get(
            "preprocessing_implementation"
        ),
        "packing_oracle_protocol": metadata.get("packing_oracle_protocol"),
        "experiment_phase": metadata.get("experiment_phase"),
        "python_version": metadata.get("python_version"),
        "gurobi_version": metadata.get("gurobi_version"),
        "threads": metadata.get("threads"),
        "mip_gap": metadata.get("mip_gap"),
        "dependency_profile": metadata.get("dependency_profile"),
        "stability_formulation": metadata.get("stability_formulation"),
        "weight_profile": json.dumps(
            metadata.get("weight_profile", {}),
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def default_manifest_path(output_csv: str | Path) -> Path:
    """Derive ``<CSV stem>.manifest.json`` from an experiment output path."""
    return Path(output_csv).with_suffix(".manifest.json")


def _experiment_row_ok(row: dict) -> bool:
    """Interpret in-memory booleans and CSV boolean strings consistently."""
    value = row.get("ok")
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def write_experiment_artifacts(
    *,
    rows: list[dict],
    output_csv: str | Path,
    metadata: dict[str, object],
    requested_matrix: dict[str, object],
    manifest_output: str | Path | None = None,
    command: list[str] | None = None,
    created_at_utc: str | None = None,
    expected_row_count: int | None = None,
) -> Path:
    """Atomically write one CSV and its reproducibility manifest."""
    if not rows:
        raise ValueError("no experiment rows were requested")
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_temporary = output_path.with_name(f".{output_path.name}.tmp")
    with output_temporary.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(output_temporary, output_path)

    manifest_path = (
        Path(manifest_output)
        if manifest_output is not None
        else default_manifest_path(output_path)
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = created_at_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    manifest = {
        "created_at_utc": timestamp,
        "command": list(command if command is not None else sys.argv),
        "output_csv": str(output_path),
        "metadata": metadata,
        "requested_matrix": requested_matrix,
        "row_count": len(rows),
        "expected_row_count": (
            len(rows) if expected_row_count is None else int(expected_row_count)
        ),
        "complete": (
            True
            if expected_row_count is None
            else len(rows) == int(expected_row_count)
        ),
        "all_ok": all(_experiment_row_ok(row) for row in rows),
    }
    manifest_temporary = manifest_path.with_name(f".{manifest_path.name}.tmp")
    with manifest_temporary.open("w", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(manifest_temporary, manifest_path)
    return manifest_path

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
            "normalized": config.USE_NORMALIZED_OPERATION_OBJECTIVE,
            "concentration": config.OPERATION_WEIGHT_CONCENTRATION,
            "balance": config.OPERATION_WEIGHT_BALANCE,
            "distance": config.OPERATION_WEIGHT_DISTANCE,
            "in_out_conflict": config.OPERATION_WEIGHT_IN_OUT_CONFLICT,
        },
        "dependency": {
            "enabled": config.DEPENDENCY_PROPAGATION_ENABLED,
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
            "wall_time_tolerance_seconds": config.WALL_TIME_TOLERANCE_SECONDS,
            "postprocessing_reserve_ratio": config.POSTPROCESSING_RESERVE_RATIO,
            "postprocessing_reserve_min_seconds": (
                config.POSTPROCESSING_RESERVE_MIN_SECONDS
            ),
            "postprocessing_reserve_max_seconds": (
                config.POSTPROCESSING_RESERVE_MAX_SECONDS
            ),
        },
    }


def collect_experiment_metadata(
    *,
    threads: int,
    mip_gap: float,
    time_limit: float,
    dependency_profile: str = "current",
) -> dict[str, object]:
    """Collect one immutable metadata record for an experiment batch."""
    return {
        **collect_git_metadata(),
        "problem_protocol": config.PROBLEM_PROTOCOL,
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
        "weight_profile": collect_weight_profile(dependency_profile),
    }


def csv_metadata_fields(metadata: dict[str, object]) -> dict[str, object]:
    """Convert shared batch metadata to stable scalar CSV fields."""
    return {
        "git_commit": metadata.get("git_commit"),
        "git_branch": metadata.get("git_branch"),
        "git_dirty": metadata.get("git_dirty"),
        "problem_protocol": metadata.get("problem_protocol"),
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

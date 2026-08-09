"""Validate or generate the complete TRE V3 confirmatory instance matrix.

The default action is a non-generating readiness check.  Actual generation
requires the frozen authorization flag, the exact freeze tag, and the explicit
``--confirm-open-formal-seeds`` acknowledgement.  Partial outputs are never
overwritten or resumed by this entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from formal_experiments import INSTANCE_PROTOCOL, sha256_file
from scripts.prepare_pnc_yangshan_v3_confirmatory_instances import (
    DEFAULT_SPEC as DEFAULT_PNC_SPEC,
    exact_git_tag,
    git_identity,
    load_confirmatory_spec,
    required_source_paths,
    validate_controlled_preflight,
)


DEFAULT_SYNTHETIC_SPEC = Path(
    "docs/specs/fully_synthetic_formal_matrix_v2.json"
)
DEFAULT_MANIFEST = Path("docs/specs/formal_run_manifest_v3.json")
DEFAULT_OUTPUT = Path("local_results/tre_v3_rc2/instances")
DEFAULT_PNC_SOURCE_ROOT = Path("local_results/protocol_v2_pnc_yangshan")
DEFAULT_ATTRIBUTE_ROOT = (
    DEFAULT_PNC_SOURCE_ROOT / "pnc_export_attribute_disaggregation"
)
DEFAULT_YARD_ROOT = DEFAULT_PNC_SOURCE_ROOT / "yangshan_calibrated_virtual_yard"


def planned_longest_temporary_path(output_root: Path) -> Path:
    """Return the longest known generated path before any seed is opened."""

    seed = max(config.FORMAL_SEEDS)
    candidates = (
        output_root
        / "pnc_yangshan"
        / "yard_high_pressure"
        / f"seed_{seed}"
        / (
            ".pnc_yangshan_yard_high_pressure_observed_n4_"
            f"seed{seed}.instance.json.tmp"
        ),
        output_root
        / "fully_synthetic"
        / "scale_pressure"
        / (
            ".synthetic_xlarge_high_pressure_e0.1_mixed_u0.55_"
            f"seed{seed}.instance.json.tmp"
        ),
        output_root
        / "fully_synthetic"
        / "initial_utilization_u065"
        / (
            ".synthetic_medium_e0.1_mixed_u0.65_"
            f"seed{seed}.instance.json.tmp"
        ),
        output_root
        / "fully_synthetic"
        / "forecast_error"
        / "error_010_booking_add_cancel"
        / (
            ".synthetic_medium_e0.1_booking_add_cancel_u0.55_"
            f"seed{seed}.instance.json.tmp"
        ),
        output_root
        / "fully_synthetic"
        / "repair_mechanism"
        / f".pressure_global_seed{seed}.instance.json.tmp",
    )
    resolved = tuple(candidate.resolve() for candidate in candidates)
    return max(resolved, key=lambda path: len(str(path)))


def validate_windows_path_budget(output_root: Path) -> dict[str, object]:
    """Fail before generation when a classic Windows path would be unsafe."""

    longest = planned_longest_temporary_path(output_root)
    length = len(str(longest))
    safe_limit = 248
    if os.name == "nt" and length > safe_limit:
        raise RuntimeError(
            "formal output root exceeds the frozen Windows path budget: "
            f"planned_length={length}, safe_limit={safe_limit}, path={longest}"
        )
    return {
        "planned_longest_temporary_path": str(longest),
        "planned_longest_temporary_path_length": length,
        "windows_safe_limit": safe_limit,
    }


def load_design(
    pnc_spec_path: Path,
    synthetic_spec_path: Path,
    manifest_path: Path,
) -> tuple[dict, dict, dict]:
    pnc_spec, _base = load_confirmatory_spec(pnc_spec_path)
    pnc_output = Path(pnc_spec["generation_gate"]["output_root"])
    if pnc_output.resolve() != (DEFAULT_OUTPUT / "pnc_yangshan").resolve():
        raise RuntimeError("PNC output root differs from the frozen RC2 root")
    synthetic = json.loads(synthetic_spec_path.read_text(encoding="utf-8"))
    if synthetic.get("schema") != "fully-synthetic-formal-matrix-v2":
        raise RuntimeError("unexpected confirmatory synthetic matrix schema")
    if tuple(synthetic.get("formal_seeds", ())) != config.FORMAL_SEEDS:
        raise RuntimeError("confirmatory synthetic seeds differ from config")
    common = synthetic.get("common", {})
    for field, expected in {
        "problem_protocol": config.PROBLEM_PROTOCOL,
        "algorithm_version": config.ALGORITHM_VERSION,
        "result_schema": config.RESULT_SCHEMA_VERSION,
        "execution_mode": config.FORMAL_EXECUTION_MODE,
    }.items():
        if common.get(field) != expected:
            raise RuntimeError(f"confirmatory synthetic identity mismatch: {field}")
    base = synthetic["base_design"]
    if sha256_file(base["path"]) != base["sha256"]:
        raise RuntimeError("historical synthetic base-design hash mismatch")
    if synthetic["counts"]["expected_total_result_rows"] != 740:
        raise RuntimeError("confirmatory synthetic row count mismatch")
    if Path(synthetic["output_root"]).resolve() != (
        DEFAULT_OUTPUT / "fully_synthetic"
    ).resolve():
        raise RuntimeError("synthetic output root differs from the frozen RC2 root")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "formal-run-manifest-v3":
        raise RuntimeError("unexpected formal manifest schema")
    if bool(manifest.get("freeze_authorization")) is not bool(
        config.FORMAL_RESULT_AUTHORIZED
    ):
        raise RuntimeError("formal authorization differs between manifest and config")
    confirmatory = manifest["evaluation_boundary"]["confirmatory_set"]
    if tuple(confirmatory["seeds"]) != config.FORMAL_SEEDS:
        raise RuntimeError("manifest confirmatory seed mismatch")
    plan = manifest["confirmatory_formal_plan"]
    if plan["expected_total_result_rows"] != 1050:
        raise RuntimeError("formal plan row count mismatch")
    if plan["semisynthetic"]["expected_result_rows"] != pnc_spec[
        "expected_counts"
    ]["total_semisynthetic_result_rows"]:
        raise RuntimeError("semi-synthetic plan count mismatch")
    if plan["fully_synthetic"]["expected_result_rows"] != synthetic[
        "counts"
    ]["expected_total_result_rows"]:
        raise RuntimeError("fully synthetic plan count mismatch")
    execution_path = Path(plan["execution_plan"])
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if execution.get("schema") != "tre-v3-formal-execution-plan-v1":
        raise RuntimeError("unexpected formal execution plan schema")
    if tuple(execution.get("formal_seeds", ())) != config.FORMAL_SEEDS:
        raise RuntimeError("formal execution plan seed mismatch")
    if execution.get("formal_freeze_tag") != config.FORMAL_FREEZE_TAG:
        raise RuntimeError("formal execution plan freeze tag mismatch")
    if execution.get("execution", {}).get("mode") != config.FORMAL_EXECUTION_MODE:
        raise RuntimeError("formal execution mode mismatch")
    if Path(execution.get("instance_root", "")).resolve() != DEFAULT_OUTPUT.resolve():
        raise RuntimeError("formal execution instance root mismatch")
    if execution.get("expected_total_rows") != 1050:
        raise RuntimeError("formal execution row count mismatch")
    return pnc_spec, synthetic, manifest


def generation_commands(
    output_root: Path,
    oracle_time: float,
    *,
    pnc_spec: Path = DEFAULT_PNC_SPEC,
    attribute_root: Path = DEFAULT_ATTRIBUTE_ROOT,
    yard_root: Path = DEFAULT_YARD_ROOT,
) -> list[list[str]]:
    python = sys.executable
    seeds = [str(seed) for seed in config.FORMAL_SEEDS]
    generic = str(ROOT / "scripts" / "prepare_formal_instances.py")
    synthetic_root = output_root / "fully_synthetic"
    commands = [[
        python,
        str(ROOT / "scripts" / "prepare_pnc_yangshan_v3_confirmatory_instances.py"),
        "--spec", str(pnc_spec),
        "--attribute-root", str(attribute_root),
        "--yard-root", str(yard_root),
        "--output-root", str(output_root / "pnc_yangshan"),
        "--oracle-time", str(oracle_time),
        "--confirm-open-formal-seeds",
    ]]
    commands.append([
        python, generic,
        "--experiment-phase", "formal",
        "--output-dir", str(synthetic_root / "scale_pressure"),
        "--confirm-open-formal-seeds",
        "synthetic",
        "--sizes", "small", "medium", "large", "xlarge",
        "--seeds", *seeds,
        "--forecast-error", "0.1",
        "--forecast-error-mode", "mixed",
        "--initial-utilization", "0.55",
        "--capacity-pressure-profiles", "ordinary", "high_pressure",
        "--oracle-time", str(oracle_time),
        "--oracle-threads", "1",
    ])
    for level in ("0.25", "0.55", "0.65"):
        commands.append([
            python, generic,
            "--experiment-phase", "formal",
            "--output-dir", str(
                synthetic_root / f"initial_utilization_u{level.replace('.', '')}"
            ),
            "--confirm-open-formal-seeds",
            "synthetic",
            "--sizes", "medium",
            "--seeds", *seeds,
            "--forecast-error", "0.1",
            "--forecast-error-mode", "mixed",
            "--initial-utilization", level,
            "--ship-volume-factor", "1.0",
            "--certify-oracle",
            "--oracle-time", str(oracle_time),
            "--oracle-threads", "1",
        ])
    forecast_profiles = (
        ("error_000_mixed", "0.0", "mixed"),
        ("error_020_mixed", "0.2", "mixed"),
        ("error_030_mixed", "0.3", "mixed"),
        ("error_010_multiplicative", "0.1", "multiplicative"),
        ("error_010_timing_shift", "0.1", "timing_shift"),
        ("error_010_booking_add_cancel", "0.1", "booking_add_cancel"),
        ("error_010_ship_correlated", "0.1", "ship_correlated"),
    )
    for name, error, mode in forecast_profiles:
        commands.append([
            python, generic,
            "--experiment-phase", "formal",
            "--output-dir", str(synthetic_root / "forecast_error" / name),
            "--confirm-open-formal-seeds",
            "synthetic",
            "--sizes", "medium",
            "--seeds", *seeds,
            "--forecast-error", error,
            "--forecast-error-mode", mode,
            "--initial-utilization", "0.55",
            "--ship-volume-factor", "1.0",
            "--certify-oracle",
            "--oracle-time", str(oracle_time),
            "--oracle-threads", "1",
        ])
    commands.append([
        python, generic,
        "--experiment-phase", "formal",
        "--output-dir", str(synthetic_root / "repair_mechanism"),
        "--confirm-open-formal-seeds",
        "pressure",
        "--levels", "nearby", "global",
        "--seeds", *seeds,
    ])
    return commands


def _read_index(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("index_schema") != "rolling-instance-index-v1":
        raise RuntimeError(f"unexpected generated index: {path}")
    if payload.get("instance_protocol") != INSTANCE_PROTOCOL:
        raise RuntimeError(f"generated instance protocol mismatch: {path}")
    if payload.get("experiment_phase") != "formal":
        raise RuntimeError(f"generated index is not formal: {path}")
    if payload.get("formal_results_authorized") is not True:
        raise RuntimeError(f"generated index lacks formal authorization: {path}")
    if int(payload.get("entry_count", -1)) != len(payload.get("entries", [])):
        raise RuntimeError(f"generated index count mismatch: {path}")
    return payload


def _relative(index_dir: Path, bundle: Path) -> str:
    return Path(os.path.relpath(bundle.resolve(), index_dir.resolve())).as_posix()


def _copy_entries(index_path: Path, target_dir: Path, **extra: str) -> list[dict]:
    payload = _read_index(index_path)
    rows = []
    for original in payload["entries"]:
        bundle = (index_path.parent / original["instance_bundle_filename"]).resolve()
        if sha256_file(bundle) != original["instance_bundle_sha256"]:
            raise RuntimeError(f"generated bundle hash mismatch: {bundle}")
        rows.append({
            **original,
            **extra,
            "instance_bundle_filename": _relative(target_dir, bundle),
        })
    return rows


def _write_index(path: Path, *, panel: str, entries: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(path)
    payload = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "experiment_phase": "formal",
        "formal_results_authorized": True,
        "formal_freeze_tag": config.FORMAL_FREEZE_TAG,
        "panel": panel,
        "entry_count": len(entries),
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def freeze_combined_indexes(output_root: Path) -> dict[str, Path]:
    synthetic_root = output_root / "fully_synthetic"
    scale = synthetic_root / "scale_pressure" / "synthetic_instance_index.json"
    u055 = (
        synthetic_root / "initial_utilization_u055" / "synthetic_instance_index.json"
    )
    scale_payload = _read_index(scale)
    medium = [
        row for row in scale_payload["entries"]
        if row.get("profile") == "medium_ordinary"
    ]
    if len(medium) != len(config.FORMAL_SEEDS):
        raise RuntimeError("new medium-ordinary ablation subset is incomplete")
    derived_dir = synthetic_root / "derived_indexes"
    derived_entries = []
    for row in medium:
        bundle = (scale.parent / row["instance_bundle_filename"]).resolve()
        derived_entries.append({
            **row,
            "instance_bundle_filename": _relative(derived_dir, bundle),
        })
    internal = derived_dir / "synthetic_internal_ablation_index.json"
    aggregate = derived_dir / "synthetic_aggregate_ablation_index.json"
    _write_index(internal, panel="internal_ablation", entries=derived_entries)
    _write_index(aggregate, panel="aggregate_ablation", entries=derived_entries)

    forecast_dir = synthetic_root / "forecast_error"
    forecast_entries = _copy_entries(
        u055, forecast_dir, forecast_profile="error_010_mixed"
    )
    for name in (
        "error_000_mixed",
        "error_020_mixed",
        "error_030_mixed",
        "error_010_multiplicative",
        "error_010_timing_shift",
        "error_010_booking_add_cancel",
        "error_010_ship_correlated",
    ):
        index = forecast_dir / name / "synthetic_instance_index.json"
        forecast_entries.extend(
            _copy_entries(index, forecast_dir, forecast_profile=name)
        )
    if len(forecast_entries) != 8 * len(config.FORMAL_SEEDS):
        raise RuntimeError("combined forecast panel is incomplete")
    forecast = forecast_dir / "synthetic_forecast_error_index.json"
    _write_index(forecast, panel="forecast_error", entries=forecast_entries)
    return {
        "internal_ablation": internal,
        "aggregate_ablation": aggregate,
        "forecast_error": forecast,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pnc-spec", type=Path, default=DEFAULT_PNC_SPEC)
    parser.add_argument(
        "--attribute-root", type=Path, default=DEFAULT_ATTRIBUTE_ROOT
    )
    parser.add_argument("--yard-root", type=Path, default=DEFAULT_YARD_ROOT)
    parser.add_argument(
        "--synthetic-spec", type=Path, default=DEFAULT_SYNTHETIC_SPEC
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--oracle-time", type=float, default=60.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-only", action="store_true")
    mode.add_argument("--generate", action="store_true")
    parser.add_argument("--confirm-open-formal-seeds", action="store_true")
    args = parser.parse_args()
    check_only = not args.generate

    if args.output_root.resolve() != DEFAULT_OUTPUT.resolve():
        raise RuntimeError(
            "the frozen RC2 design requires output root "
            f"{DEFAULT_OUTPUT}; found={args.output_root}"
        )
    git = git_identity()
    if not git["clean"]:
        raise RuntimeError("formal readiness requires a clean Git commit")
    pnc_spec, synthetic_spec, manifest = load_design(
        args.pnc_spec, args.synthetic_spec, args.manifest
    )
    _confirmed_pnc_spec, base_pnc_spec = load_confirmatory_spec(args.pnc_spec)
    missing_sources = [
        str(path)
        for path in required_source_paths(
            args.attribute_root,
            args.yard_root,
            base_pnc_spec["profiles"],
        )
        if not path.is_file()
    ]
    if missing_sources:
        raise FileNotFoundError(
            "missing frozen PNC/Yangshan source artifacts: "
            + ", ".join(missing_sources)
        )
    preflight = validate_controlled_preflight(pnc_spec)
    path_budget = validate_windows_path_budget(args.output_root)
    if args.output_root.exists():
        raise FileExistsError("confirmatory formal output root already exists")
    commands = generation_commands(
        args.output_root,
        args.oracle_time,
        pnc_spec=args.pnc_spec,
        attribute_root=args.attribute_root,
        yard_root=args.yard_root,
    )
    tag = exact_git_tag()
    gate = {
        "status": "PASS",
        "action": "no_formal_seed_opened" if check_only else "generate",
        "git": git,
        "exact_git_tag": tag,
        "required_freeze_tag": config.FORMAL_FREEZE_TAG,
        "formal_result_authorized": bool(config.FORMAL_RESULT_AUTHORIZED),
        "formal_seeds": list(config.FORMAL_SEEDS),
        "preflight": preflight,
        "path_budget": path_budget,
        "pnc_source_file_count": len(
            required_source_paths(
                args.attribute_root,
                args.yard_root,
                base_pnc_spec["profiles"],
            )
        ),
        "pnc_spec_sha256": sha256_file(args.pnc_spec),
        "synthetic_spec_sha256": sha256_file(args.synthetic_spec),
        "manifest_sha256": sha256_file(args.manifest),
        "execution_plan_sha256": sha256_file(
            Path(manifest["confirmatory_formal_plan"]["execution_plan"])
        ),
        "expected_semisynthetic_rows": pnc_spec["expected_counts"]["total_semisynthetic_result_rows"],
        "expected_fully_synthetic_rows": synthetic_spec["counts"]["expected_total_result_rows"],
        "expected_total_result_rows": manifest["confirmatory_formal_plan"]["expected_total_result_rows"],
        "output_root": str(args.output_root),
        "generation_command_count": len(commands),
    }
    if check_only:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return 0
    if not config.FORMAL_RESULT_AUTHORIZED:
        parser.error("formal instance generation is not authorized")
    if not args.confirm_open_formal_seeds:
        parser.error("generation requires --confirm-open-formal-seeds")
    if tag != config.FORMAL_FREEZE_TAG:
        parser.error(
            f"generation requires exact tag {config.FORMAL_FREEZE_TAG}; found={tag!r}"
        )

    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    derived = freeze_combined_indexes(args.output_root)
    index_paths = [
        args.output_root / "pnc_yangshan" / "pnc_yangshan_v3_all_index.json",
        args.output_root / "pnc_yangshan" / "pnc_yangshan_v3_central_main_index.json",
        args.output_root / "pnc_yangshan" / "pnc_yangshan_v3_robustness_index.json",
        args.output_root / "fully_synthetic" / "scale_pressure" / "synthetic_instance_index.json",
        args.output_root / "fully_synthetic" / "initial_utilization_u025" / "synthetic_instance_index.json",
        args.output_root / "fully_synthetic" / "initial_utilization_u055" / "synthetic_instance_index.json",
        args.output_root / "fully_synthetic" / "initial_utilization_u065" / "synthetic_instance_index.json",
        args.output_root / "fully_synthetic" / "repair_mechanism" / "pressure_instance_index.json",
        *derived.values(),
    ]
    records = [
        {"path": str(path), "sha256": sha256_file(path), "entry_count": _read_index(path)["entry_count"]}
        for path in index_paths
    ]
    generation_manifest = {
        **gate,
        "status": "PASS",
        "action": "generated_and_frozen",
        "commands": commands,
        "indexes": records,
        "generated_unique_bundle_count": 280,
    }
    manifest_path = args.output_root / "formal_instance_generation_manifest.json"
    manifest_path.write_text(
        json.dumps(generation_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "index_count": len(records),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

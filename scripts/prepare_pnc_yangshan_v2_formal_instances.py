"""Generate the frozen PNC--Yangshan V2 formal instance matrix.

This is the only authorized entry point for opening formal seeds 1000--1009.
It validates the frozen specification, clean Git state, source artifacts, and
five-method preflight audit before invoking the single-instance assembler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from formal_experiments import INSTANCE_PROTOCOL, read_instance_bundle


DATA_PROTOCOL = "pnc-yangshan-formal-instance-v2"
SPEC_SCHEMA = "pnc-yangshan-formal-instance-spec-v1"
PROFILE_ORDER = (
    "temporal_mar",
    "temporal_apr",
    "temporal_jun",
    "volume_baseline",
    "volume_low",
    "volume_high",
    "yard_observed",
    "yard_high_pressure",
)
PREFLIGHT_AUDIT = Path(
    "local_results/protocol_v2_pnc_yangshan/preflight_runs/"
    "v147_v11_five_method_three_seed/audit.json"
)
EXPECTED_PREFLIGHT_SHA256 = (
    "7ac1ecc7a621cb1136acfdf3bc9dcd308722034fd339ad9016f417259104af01"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_identity() -> dict[str, object]:
    values: dict[str, str] = {}
    for name, command in {
        "commit": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "status": ["git", "status", "--porcelain"],
    }.items():
        result = subprocess.run(
            command, cwd=ROOT, check=True, capture_output=True, text=True
        )
        values[name] = result.stdout.strip()
    return {
        "commit": values["commit"],
        "branch": values["branch"],
        "clean": not bool(values["status"]),
    }


def load_and_validate_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema") != SPEC_SCHEMA:
        raise RuntimeError("unexpected formal specification schema")
    if spec.get("data_protocol_version") != DATA_PROTOCOL:
        raise RuntimeError("formal specification data protocol mismatch")
    if tuple(spec.get("formal_seeds", ())) != tuple(config.FORMAL_SEEDS):
        raise RuntimeError("formal seed list differs from frozen configuration")
    profiles = spec.get("profiles", [])
    if tuple(row.get("profile") for row in profiles) != PROFILE_ORDER:
        raise RuntimeError("formal profile order or membership changed")
    expected = spec.get("expected_counts", {})
    if expected.get("unique_bundle_count") != len(PROFILE_ORDER) * len(
        config.FORMAL_SEEDS
    ):
        raise RuntimeError("formal expected bundle count is inconsistent")
    common = spec.get("common", {})
    if common.get("supported_sizes") != [20, 40]:
        raise RuntimeError("formal size domain changed")
    if common.get("supported_heights") != ["STD", "HIGH"]:
        raise RuntimeError("formal height domain changed")
    if common.get("yard_scope") != "yangshan_of_only":
        raise RuntimeError("formal yard scope changed")
    return spec


def validate_preflight(path: Path) -> dict:
    audit = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "status": "PASS",
        "row_count": 120,
        "instance_count": 24,
        "all_ok": True,
        "total_final_unplaced": 0,
        "validation_failures": 0,
        "online_deadline_misses": 0,
        "candidate_algorithm_version": config.ALGORITHM_VERSION,
        "external_baseline_protocol": config.EXTERNAL_BASELINE_PROTOCOL,
        "merged_csv_sha256": EXPECTED_PREFLIGHT_SHA256,
    }
    for key, value in required.items():
        if audit.get(key) != value:
            raise RuntimeError(f"five-method preflight gate mismatch: {key}")
    expected_methods = set(config.FORMAL_PRIMARY_CONFIGURATIONS)
    if set(audit.get("methods", ())) != expected_methods:
        raise RuntimeError("five-method preflight method set mismatch")
    if any(audit.get("rows_per_method", {}).get(name) != 24
           for name in expected_methods):
        raise RuntimeError("five-method preflight is incomplete")
    return audit


def profile_arguments(profile: dict) -> list[str]:
    profile_id = profile["profile"]
    scenario = {
        "volume_low": "low",
        "volume_high": "high",
    }.get(profile_id, "observed")
    return [
        "--period", profile["source_period"],
        "--start-date", profile["source_window"][0],
        "--end-date", profile["source_window"][1],
        "--call-count", "4",
        "--volume-scenario", scenario,
        "--profile-id", profile_id,
        "--yard-profile", profile["yard_profile"],
        "--selected-area-count", "40",
        "--minimum-free-factor", "3.0",
        "--forecast-error", "0.1",
        "--time-budget", "60",
    ]


def validate_generated_bundle(
    directory: Path, output_root: Path, profile: dict, seed: int
) -> dict:
    audits = list(directory.glob("assembly_audit.json"))
    bundles = list(directory.glob("*.instance.json"))
    if len(audits) != 1 or len(bundles) != 1:
        raise RuntimeError(f"incomplete generated directory: {directory}")
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    if audit.get("status") != "PASS" or not all(
        audit.get("readiness_gates", {}).values()
    ):
        raise RuntimeError(f"generated bundle failed audit: {directory}")
    if set(audit.get("selected_call_ids", ())) != set(
        profile["selected_call_ids"]
    ):
        raise RuntimeError(f"selected PNC calls changed: {directory}")
    case, metadata = read_instance_bundle(bundles[0])
    if metadata.get("seed") != seed:
        raise RuntimeError(f"generated seed mismatch: {directory}")
    if metadata.get("data_protocol_version") != DATA_PROTOCOL:
        raise RuntimeError(f"generated protocol mismatch: {directory}")
    if case.get("oracle_certificate", {}).get("classification") != "feasible":
        raise RuntimeError(f"bundle lacks a feasible integer certificate: {directory}")
    return {
        "profile": profile["profile"],
        "paper_role": profile["paper_role"],
        "seed": seed,
        "method_set": profile["method_set"],
        "instance_id": metadata["instance_id"],
        "instance_bundle_filename": bundles[0].relative_to(output_root).as_posix(),
        "instance_bundle_sha256": sha256(bundles[0]),
        "instance_case_sha256": metadata["instance_case_sha256"],
        "time_budget_seconds": metadata["time_budget_seconds"],
        "selected_call_ids": profile["selected_call_ids"],
        "source_hashes": metadata["source_hashes"],
        "oracle_classification": "feasible",
    }


def main() -> None:
    base = Path("local_results/protocol_v2_pnc_yangshan")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("docs/specs/pnc_yangshan_v2_formal_instance_spec.json"),
    )
    parser.add_argument(
        "--attribute-root",
        type=Path,
        default=base / "pnc_export_attribute_disaggregation",
    )
    parser.add_argument(
        "--yard-root",
        type=Path,
        default=base / "yangshan_calibrated_virtual_yard",
    )
    parser.add_argument("--preflight-audit", type=Path, default=PREFLIGHT_AUDIT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=base / "formal_instances_v2",
    )
    parser.add_argument("--oracle-time", type=float, default=60.0)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate pre-generation gates without instantiating formal seeds",
    )
    args = parser.parse_args()

    if not args.check_only and not config.FORMAL_RESULT_AUTHORIZED:
        parser.error(
            "formal seed generation is not authorized for algorithm "
            f"{config.ALGORITHM_VERSION}; register the untouched confirmatory "
            "set and explicitly enable FORMAL_RESULT_AUTHORIZED first"
        )

    git = git_identity()
    if not git["clean"]:
        raise RuntimeError("formal seed generation requires a clean Git commit")
    spec = load_and_validate_spec(args.spec)
    validate_preflight(args.preflight_audit)
    required_sources = (
        args.attribute_root / "manifest.json",
        args.attribute_root / "export_calls_model_ready.csv",
        args.attribute_root / "export_groups_model_ready.csv",
        args.attribute_root / "export_calls_scenarios.csv",
        args.attribute_root / "export_groups_scenarios.csv",
        args.yard_root / "manifest.json",
    )
    missing = [str(path) for path in required_sources if not path.exists()]
    for profile in spec["profiles"]:
        yard = args.yard_root / profile["yard_profile"]
        for name in ("yard_bays.csv", "initial_locked_inventory.csv"):
            if not (yard / name).exists():
                missing.append(str(yard / name))
    if missing:
        raise FileNotFoundError("missing frozen source artifacts: " + ", ".join(missing))
    if args.output_root.exists():
        raise FileExistsError(
            "formal output root already exists; overwrite and resume are forbidden"
        )

    gate = {
        "status": "PASS",
        "action": "no_formal_seed_opened" if args.check_only else "generate",
        "git": git,
        "specification": str(args.spec),
        "specification_sha256": sha256(args.spec),
        "preflight_audit": str(args.preflight_audit),
        "preflight_audit_sha256": sha256(args.preflight_audit),
        "output_root": str(args.output_root),
        "formal_seed_count": len(config.FORMAL_SEEDS),
        "profile_count": len(PROFILE_ORDER),
        "expected_bundle_count": 80,
    }
    if args.check_only:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return

    entries = []
    assembler = ROOT / "scripts" / "assemble_pnc_yangshan_v2_pilot.py"
    for profile in spec["profiles"]:
        for seed in config.FORMAL_SEEDS:
            output = args.output_root / profile["profile"] / f"seed_{seed}"
            command = [
                sys.executable,
                str(assembler),
                "--attribute-root", str(args.attribute_root),
                "--yard-root", str(args.yard_root),
                "--seed", str(seed),
                "--oracle-time", str(args.oracle_time),
                "--output-root", str(output),
                *profile_arguments(profile),
            ]
            subprocess.run(command, cwd=ROOT, check=True)
            entries.append(
                validate_generated_bundle(
                    output, args.output_root, profile, seed
                )
            )

    if len(entries) != spec["expected_counts"]["unique_bundle_count"]:
        raise RuntimeError("generated formal bundle count mismatch")
    common_index = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "data_protocol_version": DATA_PROTOCOL,
        "experiment_phase": "formal",
        "formal_results_authorized": bool(config.FORMAL_RESULT_AUTHORIZED),
        "generator_git_commit": git["commit"],
        "formal_specification_sha256": sha256(args.spec),
    }
    index_paths = {}
    partitions = {
        "all": entries,
        "central_main": [
            row for row in entries if row["method_set"] == "central_main"
        ],
        "robustness": [
            row for row in entries if row["method_set"] == "robustness"
        ],
    }
    expected_partition_counts = {"all": 80, "central_main": 10, "robustness": 70}
    for name, selected in partitions.items():
        if len(selected) != expected_partition_counts[name]:
            raise RuntimeError(f"formal {name} index count mismatch")
        index_path = args.output_root / f"pnc_yangshan_v2_{name}_index.json"
        index_path.write_text(
            json.dumps(
                {
                    **common_index,
                    "matrix_partition": name,
                    "entry_count": len(selected),
                    "entries": selected,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        index_paths[name] = {
            "path": str(index_path),
            "sha256": sha256(index_path),
            "entry_count": len(selected),
        }
    print(json.dumps({
        **gate,
        "indexes": index_paths,
        "generated_bundle_count": len(entries),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

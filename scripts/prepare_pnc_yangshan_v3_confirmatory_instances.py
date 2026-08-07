"""Prepare the registered PNC--Yangshan V3 confirmatory instance set.

The command validates the current controlled preflight, the immutable V2 data
design, the new untouched seed registration, clean Git state, and the exact
formal freeze tag.  ``--check-only`` never instantiates a formal seed.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from formal_experiments import INSTANCE_PROTOCOL
from scripts.prepare_pnc_yangshan_v2_formal_instances import (
    DATA_PROTOCOL,
    PROFILE_ORDER,
    git_identity,
    profile_arguments,
    sha256,
    validate_generated_bundle,
)


SPEC_SCHEMA = "pnc-yangshan-confirmatory-instance-spec-v1"
DEFAULT_SPEC = Path(
    "docs/specs/pnc_yangshan_v3_confirmatory_instance_spec.json"
)
DEFAULT_OUTPUT = Path(
    "local_results/protocol_v3_tre_objective/formal_instances/"
    "pnc_yangshan_confirmatory_v3"
)


def exact_git_tag() -> str | None:
    result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def load_confirmatory_spec(path: Path) -> tuple[dict, dict]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema") != SPEC_SCHEMA:
        raise RuntimeError("unexpected V3 confirmatory specification schema")
    if spec.get("data_protocol_version") != DATA_PROTOCOL:
        raise RuntimeError("V3 confirmatory data protocol mismatch")
    if tuple(spec.get("formal_seeds", ())) != tuple(config.FORMAL_SEEDS):
        raise RuntimeError("V3 confirmatory seeds differ from configuration")
    if tuple(spec.get("profile_order", ())) != PROFILE_ORDER:
        raise RuntimeError("V3 profile order changed")
    if spec.get("problem_protocol") != config.PROBLEM_PROTOCOL:
        raise RuntimeError("V3 problem protocol mismatch")
    if spec.get("algorithm_version") != config.ALGORITHM_VERSION:
        raise RuntimeError("V3 algorithm version mismatch")
    if spec.get("result_schema") != config.RESULT_SCHEMA_VERSION:
        raise RuntimeError("V3 result schema mismatch")

    base_record = spec["base_data_design"]
    base_path = Path(base_record["path"])
    if sha256(base_path) != base_record["sha256"]:
        raise RuntimeError("base PNC--Yangshan data-design hash mismatch")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    profiles = base.get("profiles", [])
    if tuple(row.get("profile") for row in profiles) != PROFILE_ORDER:
        raise RuntimeError("base PNC--Yangshan profile design changed")
    if base.get("data_protocol_version") != DATA_PROTOCOL:
        raise RuntimeError("base PNC--Yangshan data protocol changed")

    counts = spec["expected_counts"]
    if counts.get("unique_bundle_count") != len(PROFILE_ORDER) * len(
        config.FORMAL_SEEDS
    ):
        raise RuntimeError("V3 expected bundle count mismatch")
    if counts.get("total_semisynthetic_result_rows") != 310:
        raise RuntimeError("V3 semi-synthetic result count mismatch")
    return spec, base


def _integer(row: dict, field: str) -> int:
    value = row.get(field, "")
    return int(float(value or 0))


def validate_controlled_preflight(spec: dict) -> dict:
    gate = spec["preflight_gate"]
    csv_path = Path(gate["csv"])
    manifest_path = Path(gate["manifest"])
    if not csv_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("controlled candidate-v5 preflight is missing")
    if sha256(csv_path) != gate["csv_sha256"]:
        raise RuntimeError("controlled preflight CSV hash mismatch")
    if sha256(manifest_path) != gate["manifest_sha256"]:
        raise RuntimeError("controlled preflight manifest hash mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is not True or manifest.get("all_ok") is not True:
        raise RuntimeError("controlled preflight manifest did not pass")
    if int(manifest.get("row_count", -1)) != int(gate["required_rows"]):
        raise RuntimeError("controlled preflight row count mismatch")
    metadata = manifest.get("metadata", {})
    for field, expected in {
        "problem_protocol": config.PROBLEM_PROTOCOL,
        "algorithm_version": config.ALGORITHM_VERSION,
        "result_schema_version": config.RESULT_SCHEMA_VERSION,
        "operation_weight_profile": config.OPERATION_WEIGHT_PROFILE,
    }.items():
        if metadata.get(field) != expected:
            raise RuntimeError(f"controlled preflight identity mismatch: {field}")

    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != int(gate["required_rows"]):
        raise RuntimeError("controlled preflight CSV is incomplete")
    methods = Counter(row.get("configuration") for row in rows)
    if methods != Counter({name: 24 for name in config.FORMAL_PRIMARY_CONFIGURATIONS}):
        raise RuntimeError("controlled preflight method matrix mismatch")
    if any(str(row.get("ok", "")).lower() != "true" for row in rows):
        raise RuntimeError("controlled preflight contains a failed row")
    failure_fields = (
        "online_deadline_miss_count",
        "validation_failure_count",
        "no_incumbent_count",
        "realized_unplaced",
    )
    if any(_integer(row, field) for row in rows for field in failure_fields):
        raise RuntimeError("controlled preflight contains a gate failure")
    if any(
        row.get("problem_protocol") != config.PROBLEM_PROTOCOL
        or row.get("algorithm_version") != config.ALGORITHM_VERSION
        or row.get("result_schema_version") != config.RESULT_SCHEMA_VERSION
        or row.get("operation_weight_profile") != config.OPERATION_WEIGHT_PROFILE
        for row in rows
    ):
        raise RuntimeError("controlled preflight row identities are mixed")
    return {
        "csv": str(csv_path),
        "csv_sha256": gate["csv_sha256"],
        "manifest": str(manifest_path),
        "manifest_sha256": gate["manifest_sha256"],
        "row_count": len(rows),
        "rows_per_method": dict(sorted(methods.items())),
    }


def required_source_paths(
    attribute_root: Path,
    yard_root: Path,
    profiles: list[dict],
) -> list[Path]:
    paths = [
        attribute_root / "manifest.json",
        attribute_root / "export_calls_model_ready.csv",
        attribute_root / "export_groups_model_ready.csv",
        attribute_root / "export_calls_scenarios.csv",
        attribute_root / "export_groups_scenarios.csv",
        yard_root / "manifest.json",
    ]
    for profile in profiles:
        yard = yard_root / profile["yard_profile"]
        paths.extend((yard / "yard_bays.csv", yard / "initial_locked_inventory.csv"))
    return paths


def main() -> None:
    base = Path("local_results/protocol_v2_pnc_yangshan")
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
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
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--oracle-time", type=float, default=60.0)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--confirm-open-formal-seeds", action="store_true")
    args = parser.parse_args()

    git = git_identity()
    if not git["clean"]:
        raise RuntimeError("formal seed preparation requires a clean Git commit")
    spec, base_spec = load_confirmatory_spec(args.spec)
    preflight = validate_controlled_preflight(spec)
    profiles = base_spec["profiles"]
    missing = [
        str(path)
        for path in required_source_paths(args.attribute_root, args.yard_root, profiles)
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("missing frozen source artifacts: " + ", ".join(missing))
    if args.output_root.exists():
        raise FileExistsError("confirmatory output root already exists")

    tag = exact_git_tag()
    gate = {
        "status": "PASS",
        "action": "no_formal_seed_opened" if args.check_only else "generate",
        "git": git,
        "exact_git_tag": tag,
        "required_freeze_tag": config.FORMAL_FREEZE_TAG,
        "formal_result_authorized": bool(config.FORMAL_RESULT_AUTHORIZED),
        "specification": str(args.spec),
        "specification_sha256": sha256(args.spec),
        "base_specification_sha256": spec["base_data_design"]["sha256"],
        "preflight": preflight,
        "output_root": str(args.output_root),
        "formal_seeds": list(config.FORMAL_SEEDS),
        "profile_count": len(PROFILE_ORDER),
        "expected_bundle_count": spec["expected_counts"]["unique_bundle_count"],
    }
    if args.check_only:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return
    if not config.FORMAL_RESULT_AUTHORIZED:
        parser.error("formal instance generation is not authorized")
    if not args.confirm_open_formal_seeds:
        parser.error("generation requires --confirm-open-formal-seeds")
    if tag != config.FORMAL_FREEZE_TAG:
        parser.error(
            f"generation requires exact tag {config.FORMAL_FREEZE_TAG}; found={tag!r}"
        )

    entries = []
    assembler = ROOT / "scripts" / "assemble_pnc_yangshan_v2_pilot.py"
    for profile in profiles:
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
                validate_generated_bundle(output, args.output_root, profile, seed)
            )

    if len(entries) != spec["expected_counts"]["unique_bundle_count"]:
        raise RuntimeError("generated V3 bundle count mismatch")
    common = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "data_protocol_version": DATA_PROTOCOL,
        "experiment_phase": "formal",
        "formal_results_authorized": True,
        "formal_freeze_tag": config.FORMAL_FREEZE_TAG,
        "generator_git_commit": git["commit"],
        "formal_specification_sha256": sha256(args.spec),
    }
    partitions = {
        "all": entries,
        "central_main": [row for row in entries if row["method_set"] == "central_main"],
        "robustness": [row for row in entries if row["method_set"] == "robustness"],
    }
    expected_counts = {"all": 80, "central_main": 10, "robustness": 70}
    indexes = {}
    for name, selected in partitions.items():
        if len(selected) != expected_counts[name]:
            raise RuntimeError(f"V3 {name} partition count mismatch")
        path = args.output_root / f"pnc_yangshan_v3_{name}_index.json"
        path.write_text(
            json.dumps(
                {**common, "matrix_partition": name, "entry_count": len(selected), "entries": selected},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        indexes[name] = {"path": str(path), "sha256": sha256(path), "entry_count": len(selected)}
    print(json.dumps({**gate, "indexes": indexes, "generated_bundle_count": len(entries)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

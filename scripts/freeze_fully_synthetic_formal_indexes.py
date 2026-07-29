"""Create derived ablation indexes and audit the full synthetic matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from formal_experiments import INSTANCE_PROTOCOL, read_instance_bundle, sha256_file


SPEC_PATH = Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
DEFAULT_OUTPUT = Path("local_results/formal/instances_v2/derived_indexes")


def git_identity() -> dict[str, object]:
    values = {}
    for key, command in {
        "commit": ["git", "rev-parse", "HEAD"],
        "branch": ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        "status": ["git", "status", "--porcelain"],
    }.items():
        result = subprocess.run(
            command, cwd=ROOT, check=True, capture_output=True, text=True
        )
        values[key] = result.stdout.strip()
    return {
        "commit": values["commit"],
        "branch": values["branch"],
        "clean": not bool(values["status"]),
    }


def relative_path(base: Path, target: Path) -> str:
    return Path(os.path.relpath(target.resolve(), base.resolve())).as_posix()


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema") != "fully-synthetic-formal-matrix-v1":
        raise RuntimeError("unexpected fully synthetic matrix schema")
    if tuple(spec.get("formal_seeds", ())) != tuple(config.FORMAL_SEEDS):
        raise RuntimeError("formal seed list mismatch")
    if spec["counts"]["expected_total_result_rows"] != 740:
        raise RuntimeError("frozen result count mismatch")
    return spec


def panel_map(spec: dict) -> dict[str, dict]:
    return {row["panel"]: row for row in spec["panels"]}


def read_index(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("index_schema") != "rolling-instance-index-v1":
        raise RuntimeError(f"unexpected index schema: {path}")
    if payload.get("instance_protocol") != INSTANCE_PROTOCOL:
        raise RuntimeError(f"instance protocol mismatch: {path}")
    if payload.get("experiment_phase") != "formal":
        raise RuntimeError(f"non-formal index: {path}")
    if payload.get("entry_count") != len(payload.get("entries", [])):
        raise RuntimeError(f"index entry count mismatch: {path}")
    return payload


def resolve_entry(index_path: Path, entry: dict) -> Path:
    return (index_path.parent / entry["instance_bundle_filename"]).resolve()


def select_medium_ordinary(index_path: Path) -> list[dict]:
    payload = read_index(index_path)
    selected = [
        entry for entry in payload["entries"]
        if entry.get("profile") == "medium_ordinary"
    ]
    if len(selected) != len(config.FORMAL_SEEDS):
        raise RuntimeError("medium-ordinary scale subset must contain ten seeds")
    if {entry["seed"] for entry in selected} != set(config.FORMAL_SEEDS):
        raise RuntimeError("medium-ordinary scale subset seed mismatch")
    return selected


def write_derived_index(
    path: Path,
    *,
    panel: str,
    source_index: Path,
    source_entries: list[dict],
    spec_hash: str,
    git_commit: str,
) -> None:
    entries = []
    for entry in source_entries:
        bundle = resolve_entry(source_index, entry)
        if sha256_file(bundle) != entry["instance_bundle_sha256"]:
            raise RuntimeError(f"source bundle hash mismatch: {bundle}")
        entries.append({
            **entry,
            "instance_bundle_filename": relative_path(path.parent, bundle),
        })
    payload = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "experiment_phase": "formal",
        "matrix_specification_sha256": spec_hash,
        "generator_git_commit": git_commit,
        "panel": panel,
        "source_index": {
            "path": str(source_index),
            "sha256": sha256_file(source_index),
        },
        "entry_count": len(entries),
        "entries": entries,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def audit_index(
    index_path: Path,
    *,
    certificate_required: bool,
) -> tuple[dict, set[str]]:
    payload = read_index(index_path)
    bundle_hashes = set()
    seeds = Counter()
    certificate_pass = 0
    for entry in payload["entries"]:
        bundle = resolve_entry(index_path, entry)
        if sha256_file(bundle) != entry["instance_bundle_sha256"]:
            raise RuntimeError(f"bundle/index hash mismatch: {bundle}")
        case, metadata = read_instance_bundle(bundle)
        if metadata["instance_case_sha256"] != entry["instance_case_sha256"]:
            raise RuntimeError(f"case/index hash mismatch: {bundle}")
        seeds[metadata["seed"]] += 1
        bundle_hashes.add(metadata["instance_bundle_sha256"])
        classification = case.get("oracle_certificate", {}).get(
            "classification"
        )
        if classification == "feasible":
            certificate_pass += 1
        elif certificate_required:
            raise RuntimeError(f"uncertified performance bundle: {bundle}")
    return {
        "path": str(index_path),
        "sha256": sha256_file(index_path),
        "entry_count": len(payload["entries"]),
        "seed_counts": dict(sorted(seeds.items())),
        "certificate_required": certificate_required,
        "certificate_pass_count": certificate_pass,
    }, bundle_hashes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    git = git_identity()
    if not git["clean"]:
        raise RuntimeError("formal index freeze requires a clean Git commit")
    spec = load_spec(args.spec)
    panels = panel_map(spec)
    scale_index = Path(panels["scale_pressure"]["index"])
    forecast_index = Path(
        "local_results/formal/instances_v2/synthetic_forecast_error/"
        "synthetic_forecast_error_index.json"
    )
    required = [
        scale_index,
        *(Path(path) for path in panels["initial_utilization"]["indexes"]),
        forecast_index,
        Path(panels["repair_mechanism"]["index"]),
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing formal indexes: " + ", ".join(missing))
    if args.output_root.exists():
        raise FileExistsError("derived-index output root already exists")
    subset = select_medium_ordinary(scale_index)
    gate = {
        "status": "PASS",
        "action": "check_only" if args.check_only else "freeze_and_audit",
        "git": git,
        "matrix_specification_sha256": sha256_file(args.spec),
        "medium_ordinary_subset_count": len(subset),
        "expected_total_result_rows": spec["counts"][
            "expected_total_result_rows"
        ],
        "output_root": str(args.output_root),
    }
    if args.check_only:
        print(json.dumps(gate, indent=2))
        return

    args.output_root.mkdir(parents=True, exist_ok=False)
    derived = {
        "internal_ablation": args.output_root
        / "synthetic_internal_ablation_index.json",
        "aggregate_ablation": args.output_root
        / "synthetic_aggregate_ablation_index.json",
    }
    for panel, path in derived.items():
        write_derived_index(
            path,
            panel=panel,
            source_index=scale_index,
            source_entries=subset,
            spec_hash=sha256_file(args.spec),
            git_commit=str(git["commit"]),
        )

    audit_targets = [
        ("scale_pressure", scale_index, True),
        *[
            ("initial_utilization", Path(path), True)
            for path in panels["initial_utilization"]["indexes"]
        ],
        ("forecast_error", forecast_index, True),
        ("internal_ablation", derived["internal_ablation"], True),
        ("aggregate_ablation", derived["aggregate_ablation"], True),
        (
            "repair_mechanism",
            Path(panels["repair_mechanism"]["index"]),
            False,
        ),
    ]
    records = []
    performance_hashes: set[str] = set()
    mechanism_hashes: set[str] = set()
    for panel, index_path, certificate_required in audit_targets:
        record, hashes = audit_index(
            index_path, certificate_required=certificate_required
        )
        record["panel"] = panel
        records.append(record)
        if panel == "repair_mechanism":
            mechanism_hashes.update(hashes)
        else:
            performance_hashes.update(hashes)
    counts = spec["counts"]
    checks = {
        "unique_performance_bundle_count": (
            len(performance_hashes)
            == counts["unique_performance_bundles_after_generation"]
        ),
        "mechanism_bundle_count": (
            len(mechanism_hashes) == counts["mechanism_bundles"]
        ),
        "performance_mechanism_disjoint": performance_hashes.isdisjoint(
            mechanism_hashes
        ),
        "expected_result_rows": counts["expected_total_result_rows"] == 740,
        "derived_indexes_each_ten": all(
            read_index(path)["entry_count"] == 10 for path in derived.values()
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"fully synthetic readiness checks failed: {checks}")
    audit = {
        **gate,
        "status": "PASS",
        "checks": checks,
        "unique_performance_bundle_count": len(performance_hashes),
        "mechanism_bundle_count": len(mechanism_hashes),
        "index_records": records,
        "derived_indexes": {
            panel: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for panel, path in derived.items()
        },
    }
    audit_path = args.output_root / "fully_synthetic_readiness_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS",
        "audit": str(audit_path),
        "audit_sha256": sha256_file(audit_path),
        "unique_performance_bundle_count": len(performance_hashes),
        "mechanism_bundle_count": len(mechanism_hashes),
        "expected_result_rows": 740,
        "derived_indexes": audit["derived_indexes"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

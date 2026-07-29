"""Generate and freeze the missing fully synthetic forecast-error panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from formal_experiments import INSTANCE_PROTOCOL, read_instance_bundle, sha256_file


SPEC_PATH = Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
BASELINE_INDEX = Path(
    "local_results/formal/instances/synthetic_utilization_u055/"
    "synthetic_instance_index.json"
)
DEFAULT_OUTPUT = Path(
    "local_results/formal/instances_v2/synthetic_forecast_error"
)


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


def load_forecast_panel(spec_path: Path) -> tuple[dict, dict]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("schema") != "fully-synthetic-formal-matrix-v1":
        raise RuntimeError("unexpected fully synthetic matrix schema")
    if tuple(spec.get("formal_seeds", ())) != tuple(config.FORMAL_SEEDS):
        raise RuntimeError("formal seed list changed")
    panel = next(
        row for row in spec["panels"] if row["panel"] == "forecast_error"
    )
    identities = {
        (row["forecast_error"], row["forecast_error_mode"])
        for row in (
            panel["magnitude_profiles"]
            + panel["mechanism_profiles_at_error_010"]
        )
    }
    if len(identities) != 8 or panel["unique_profile_count"] != 8:
        raise RuntimeError("forecast profile count mismatch")
    if panel["missing_bundle_count"] != (
        len(panel["profiles_to_generate"]) * len(config.FORMAL_SEEDS)
    ):
        raise RuntimeError("missing forecast bundle count mismatch")
    return spec, panel


def profile_map(panel: dict) -> dict[str, dict]:
    rows = (
        panel["magnitude_profiles"]
        + panel["mechanism_profiles_at_error_010"]
    )
    return {row["profile"]: row for row in rows}


def relative_bundle_path(index_dir: Path, bundle: Path) -> str:
    return Path(os.path.relpath(bundle.resolve(), index_dir.resolve())).as_posix()


def verified_entries(
    index_path: Path,
    *,
    combined_dir: Path,
    forecast_profile: str,
) -> list[dict]:
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if payload.get("experiment_phase") != "formal":
        raise RuntimeError(f"non-formal source index: {index_path}")
    entries = []
    for original in payload["entries"]:
        bundle = (index_path.parent / original["instance_bundle_filename"]).resolve()
        if sha256_file(bundle) != original["instance_bundle_sha256"]:
            raise RuntimeError(f"bundle hash mismatch: {bundle}")
        case, metadata = read_instance_bundle(bundle)
        if case.get("oracle_certificate", {}).get("classification") != "feasible":
            raise RuntimeError(f"forecast bundle is not integer-certified: {bundle}")
        if metadata.get("seed") not in config.FORMAL_SEEDS:
            raise RuntimeError(f"unexpected forecast seed: {bundle}")
        entries.append({
            **original,
            "forecast_profile": forecast_profile,
            "instance_bundle_filename": relative_bundle_path(
                combined_dir, bundle
            ),
        })
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--baseline-index", type=Path, default=BASELINE_INDEX)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--oracle-time", type=float, default=60.0)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    git = git_identity()
    if not git["clean"]:
        raise RuntimeError("formal forecast generation requires a clean Git commit")
    spec, panel = load_forecast_panel(args.spec)
    profiles = profile_map(panel)
    if not args.baseline_index.exists():
        raise FileNotFoundError(args.baseline_index)
    if args.output_root.exists():
        raise FileExistsError(
            "forecast output root already exists; overwrite is forbidden"
        )
    gate = {
        "status": "PASS",
        "action": "check_only" if args.check_only else "generate",
        "git": git,
        "specification_sha256": sha256_file(args.spec),
        "baseline_index_sha256": sha256_file(args.baseline_index),
        "missing_profile_count": len(panel["profiles_to_generate"]),
        "missing_bundle_count": panel["missing_bundle_count"],
        "expected_combined_bundle_count": panel["bundle_count"],
        "output_root": str(args.output_root),
    }
    if args.check_only:
        print(json.dumps(gate, indent=2))
        return

    source_indexes: list[tuple[str, Path]] = [
        ("error_010_mixed", args.baseline_index)
    ]
    generator = ROOT / "scripts" / "prepare_formal_instances.py"
    seeds = [str(seed) for seed in config.FORMAL_SEEDS]
    for profile_name in panel["profiles_to_generate"]:
        row = profiles[profile_name]
        output = args.output_root / profile_name
        command = [
            sys.executable,
            str(generator),
            "--experiment-phase", "formal",
            "--output-dir", str(output),
            "synthetic",
            "--sizes", "medium",
            "--seeds", *seeds,
            "--forecast-error", str(row["forecast_error"]),
            "--forecast-error-mode", row["forecast_error_mode"],
            "--initial-utilization", "0.55",
            "--ship-volume-factor", "1.0",
            "--certify-oracle",
            "--oracle-time", str(args.oracle_time),
            "--oracle-threads", "1",
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        source_indexes.append(
            (profile_name, output / "synthetic_instance_index.json")
        )

    entries = []
    source_records = []
    for profile_name, index_path in source_indexes:
        selected = verified_entries(
            index_path,
            combined_dir=args.output_root,
            forecast_profile=profile_name,
        )
        if len(selected) != len(config.FORMAL_SEEDS):
            raise RuntimeError(f"forecast profile is incomplete: {profile_name}")
        entries.extend(selected)
        source_records.append({
            "forecast_profile": profile_name,
            "path": str(index_path),
            "sha256": sha256_file(index_path),
            "entry_count": len(selected),
        })
    if len(entries) != panel["bundle_count"]:
        raise RuntimeError("combined forecast panel count mismatch")
    identities = {
        (entry["forecast_profile"], entry["seed"]) for entry in entries
    }
    if len(identities) != len(entries):
        raise RuntimeError("duplicate forecast profile-seed identity")

    combined = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "experiment_phase": "formal",
        "matrix_schema": spec["schema"],
        "matrix_specification_sha256": sha256_file(args.spec),
        "generator_git_commit": git["commit"],
        "panel": "forecast_error",
        "entry_count": len(entries),
        "source_indexes": source_records,
        "entries": entries,
    }
    index_path = args.output_root / "synthetic_forecast_error_index.json"
    temporary = index_path.with_name(f".{index_path.name}.tmp")
    temporary.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, index_path)
    print(json.dumps({
        **gate,
        "combined_index": str(index_path),
        "combined_index_sha256": sha256_file(index_path),
        "generated_bundle_count": panel["missing_bundle_count"],
        "combined_bundle_count": len(entries),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

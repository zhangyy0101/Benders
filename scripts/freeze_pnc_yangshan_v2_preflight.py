"""Verify and freeze the accepted PNC--Yangshan V2 preflight bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formal_experiments import INSTANCE_PROTOCOL, read_instance_bundle


DATA_PROTOCOL = "pnc-yangshan-formal-instance-v2"
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
PAPER_ROLES = {
    "temporal_mar": ["temporal_robustness"],
    "temporal_apr": ["temporal_robustness"],
    "temporal_jun": ["temporal_robustness"],
    "volume_baseline": [
        "temporal_robustness_may",
        "volume_sensitivity_baseline",
        "yard_sensitivity_capacity_relief",
    ],
    "volume_low": ["volume_sensitivity_low"],
    "volume_high": ["volume_sensitivity_high"],
    "yard_observed": ["yard_sensitivity_observed"],
    "yard_high_pressure": ["yard_sensitivity_high_pressure"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/"
            "assembled_instances/preflight"
        ),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    entries = []
    for profile in PROFILE_ORDER:
        directory = args.root / profile
        audit_path = directory / "assembly_audit.json"
        bundles = list(directory.glob("*.instance.json"))
        if len(bundles) != 1 or not audit_path.exists():
            raise RuntimeError(f"incomplete profile directory: {profile}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("status") != "PASS" or not all(
            audit.get("readiness_gates", {}).values()
        ):
            raise RuntimeError(f"failed readiness gates: {profile}")
        bundle = bundles[0]
        case, metadata = read_instance_bundle(bundle)
        if case.get("data_protocol_version") != DATA_PROTOCOL:
            raise RuntimeError(f"data protocol mismatch: {profile}")
        if case["oracle_certificate"]["classification"] != "feasible":
            raise RuntimeError(f"uncertified bundle: {profile}")
        entries.append({
            "profile": profile,
            "paper_roles": PAPER_ROLES[profile],
            "instance_id": metadata["instance_id"],
            "instance_bundle_filename": str(
                bundle.relative_to(args.root).as_posix()
            ),
            "instance_bundle_sha256": sha256(bundle),
            "instance_case_sha256": metadata["instance_case_sha256"],
            "seed": metadata["seed"],
            "time_budget_seconds": metadata["time_budget_seconds"],
            "source_period": metadata["source_period"],
            "volume_scenario": metadata["volume_scenario"],
            "yard_profile": metadata["yard_profile"],
        })
    payload = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "data_protocol_version": DATA_PROTOCOL,
        "experiment_phase": "preflight",
        "formal_results_authorized": False,
        "entry_count": len(entries),
        "entries": entries,
    }
    output = (
        args.root / "pnc_yangshan_v2_semisynthetic_preflight_index.json"
    )
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"frozen index already exists: {output}")
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "index": str(output),
        "entry_count": len(entries),
        "sha256": sha256(output),
    }, indent=2))


if __name__ == "__main__":
    main()

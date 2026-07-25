"""Frozen instance bundles and source contracts for publication experiments."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from config import FORMAL_PUBLIC_WINDOWS, FORMAL_TIME_BUDGETS_SECONDS
from scripts.run_portmis_end_to_end import (
    build_portmis_rolling_case,
    select_calibrated_window,
)


INSTANCE_BUNDLE_SCHEMA = "rolling-instance-bundle-v1"
INSTANCE_PROTOCOL = "rolling-formal-instances-v1"
PORTMIS_SOURCE_CONTRACT = "portmis-fixed-source-snapshot-v1"


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 of the exact archived bytes."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, tuple):
        return {
            "__type__": "tuple",
            "items": [_canonical_encode(item) for item in value],
        }
    if isinstance(value, set):
        items = [_canonical_encode(item) for item in value]
        items.sort(key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        return {"__type__": "set", "items": items}
    if isinstance(value, list):
        return [_canonical_encode(item) for item in value]
    if isinstance(value, dict):
        items = [
            [_canonical_encode(key), _canonical_encode(item)]
            for key, item in value.items()
        ]
        items.sort(key=lambda pair: json.dumps(
            pair[0], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        return {"__type__": "dict", "items": items}
    raise TypeError(f"unsupported instance value type: {type(value).__name__}")


def _canonical_decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_canonical_decode(item) for item in value]
    if not isinstance(value, dict) or "__type__" not in value:
        return value
    kind = value["__type__"]
    if kind == "tuple":
        return tuple(_canonical_decode(item) for item in value["items"])
    if kind == "set":
        return {_canonical_decode(item) for item in value["items"]}
    if kind == "dict":
        return {
            _canonical_decode(key): _canonical_decode(item)
            for key, item in value["items"]
        }
    raise ValueError(f"unknown canonical type tag: {kind}")


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def case_sha256(case: dict) -> str:
    """Hash the mathematical/simulation instance independently of its filename."""
    return hashlib.sha256(_canonical_bytes(_canonical_encode(case))).hexdigest()


def write_instance_bundle(
    path: str | Path,
    *,
    case: dict,
    metadata: dict[str, object],
) -> dict[str, object]:
    """Atomically archive one exact case and return its immutable identity."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded_case = _canonical_encode(case)
    case_hash = hashlib.sha256(_canonical_bytes(encoded_case)).hexdigest()
    payload = {
        "bundle_schema": INSTANCE_BUNDLE_SCHEMA,
        "instance_protocol": INSTANCE_PROTOCOL,
        "metadata": metadata,
        "case_sha256": case_hash,
        "case": encoded_case,
    }
    raw = _canonical_bytes(payload)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return {
        **metadata,
        "instance_bundle_path": path.as_posix(),
        "instance_bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "instance_case_sha256": case_hash,
    }


def read_instance_bundle(
    path: str | Path,
) -> tuple[dict, dict[str, object]]:
    """Load a bundle and reject schema, payload, or hash inconsistencies."""
    path = Path(path)
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("bundle_schema") != INSTANCE_BUNDLE_SCHEMA:
        raise ValueError(f"unsupported instance bundle schema: {path}")
    if payload.get("instance_protocol") != INSTANCE_PROTOCOL:
        raise ValueError(f"unsupported instance protocol: {path}")
    encoded_case = payload["case"]
    actual_case_hash = hashlib.sha256(_canonical_bytes(encoded_case)).hexdigest()
    if actual_case_hash != payload.get("case_sha256"):
        raise ValueError(f"instance case hash mismatch: {path}")
    metadata = dict(payload.get("metadata") or {})
    metadata.update({
        "instance_protocol": payload["instance_protocol"],
        "instance_bundle_path": path.as_posix(),
        "instance_bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "instance_case_sha256": actual_case_hash,
    })
    return _canonical_decode(encoded_case), metadata


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_portmis_source(
    calibration_dir: str | Path,
    *,
    source_manifest: str | Path | None = None,
    require_publication_ready: bool = False,
) -> dict[str, object]:
    """Verify every frozen calibration artifact and its source declaration."""
    calibration_dir = Path(calibration_dir)
    calibration_manifest_path = calibration_dir / "manifest.json"
    calibration_manifest = _read_json(calibration_manifest_path)
    verified_outputs: dict[str, str] = {}
    for name, declaration in calibration_manifest.get("outputs", {}).items():
        path = calibration_dir / name
        if not path.exists():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != declaration.get("sha256"):
            raise ValueError(f"calibration hash mismatch: {path}")
        verified_outputs[name] = actual
    calibration_audit_path = calibration_dir / "audit.json"
    calibration_audit = _read_json(calibration_audit_path)
    if calibration_audit.get("calibration_status") != "PASS":
        raise ValueError("PORT-MIS demand calibration audit did not pass")

    source_manifest_path = (
        Path(source_manifest)
        if source_manifest is not None
        else calibration_dir.parent / "manifest.json"
    )
    source = _read_json(source_manifest_path)
    for name, declaration in source.get("raw_files", {}).items():
        raw_path = source_manifest_path.parent / name
        if not raw_path.exists():
            raise FileNotFoundError(raw_path)
        if sha256_file(raw_path) != declaration.get("sha256"):
            raise ValueError(f"raw source hash mismatch: {raw_path}")

    publication_ready = bool(source.get("publication_ready", False)) and not bool(
        source.get("pilot_only_undocumented_endpoint", False)
    )
    if publication_ready:
        if source.get("schema") != PORTMIS_SOURCE_CONTRACT:
            raise ValueError(
                "publication-ready PORT-MIS manifest has an unsupported schema"
            )
        missing = [
            field
            for field in (
                "official_data_page",
                "extraction_method",
                "query",
                "raw_files",
            )
            if not source.get(field)
        ]
        if missing:
            raise ValueError(
                "publication-ready PORT-MIS manifest is incomplete: "
                + ", ".join(missing)
            )
    if require_publication_ready and not publication_ready:
        raise ValueError(
            "PORT-MIS source is verified but provisional: formal public-data "
            "runs require publication_ready=true and "
            "pilot_only_undocumented_endpoint=false in the fixed source manifest"
        )
    fingerprint_payload = {
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "calibration_manifest_sha256": sha256_file(calibration_manifest_path),
        "verified_outputs": verified_outputs,
    }
    source_fingerprint = hashlib.sha256(
        _canonical_bytes(fingerprint_payload)
    ).hexdigest()
    return {
        "source_contract": PORTMIS_SOURCE_CONTRACT,
        "source_manifest_path": source_manifest_path.as_posix(),
        "source_manifest_sha256": fingerprint_payload[
            "source_manifest_sha256"
        ],
        "calibration_manifest_path": calibration_manifest_path.as_posix(),
        "calibration_manifest_sha256": fingerprint_payload[
            "calibration_manifest_sha256"
        ],
        "source_snapshot_sha256": source_fingerprint,
        "source_publication_ready": publication_ready,
        "pilot_only_undocumented_endpoint": bool(
            source.get("pilot_only_undocumented_endpoint", False)
        ),
        "verified_outputs": verified_outputs,
        "calibration_protocol": calibration_audit.get("protocol_version"),
        "calibration_scenario_assumptions": calibration_audit.get(
            "scenario_assumptions", {}
        ),
        "calibration_derived_targets": calibration_audit.get(
            "derived_targets", {}
        ),
    }


def build_portmis_window_case(
    calibration_dir: str | Path,
    *,
    window_id: str,
    seed: int,
    forecast_error: float = 0.10,
    forecast_error_mode: str = "multiplicative",
    initial_utilization: float = 0.25,
    calibration_scenario_id: str = "central",
    source_manifest: str | Path | None = None,
    require_publication_ready: bool = False,
) -> tuple[dict, dict[str, object]]:
    """Build one fixed public-data-driven window and complete provenance."""
    if window_id not in FORMAL_PUBLIC_WINDOWS:
        raise ValueError(
            f"window_id must be one of {tuple(FORMAL_PUBLIC_WINDOWS)}"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", calibration_scenario_id):
        raise ValueError(
            "calibration_scenario_id must contain only letters, digits, "
            "periods, underscores, or hyphens"
        )
    calibration_dir = Path(calibration_dir)
    source = verify_portmis_source(
        calibration_dir,
        source_manifest=source_manifest,
        require_publication_ready=require_publication_ready,
    )
    calls = _read_csv(calibration_dir / "calibrated_call_demand.csv")
    groups = _read_csv(calibration_dir / "calibrated_group_demand.csv")
    spec = FORMAL_PUBLIC_WINDOWS[window_id]
    selected_calls, selected_groups = select_calibrated_window(
        calls,
        groups,
        start_date=spec["start_date"],
        end_date=spec["end_date"],
    )
    case, adapter_audit = build_portmis_rolling_case(
        selected_calls,
        selected_groups,
        seed=seed,
        num_blocks=int(spec["num_blocks"]),
        bays_per_block=int(spec["bays_per_block"]),
        bay_capacity=int(spec["bay_capacity"]),
        initial_utilization=initial_utilization,
        forecast_error=forecast_error,
        forecast_error_mode=forecast_error_mode,
    )
    instance_id = f"{window_id}_{calibration_scenario_id}_seed{seed}"
    case.update({
        "instance_id": instance_id,
        "instance_family": "public_data_calibrated_semi_synthetic",
        "instance_protocol": INSTANCE_PROTOCOL,
        "source_window_id": window_id,
        "calibration_scenario_id": calibration_scenario_id,
    })
    metadata = {
        "instance_id": instance_id,
        "instance_family": case["instance_family"],
        "instance_protocol": INSTANCE_PROTOCOL,
        "profile": window_id,
        "seed": seed,
        "time_budget_seconds": FORMAL_TIME_BUDGETS_SECONDS[window_id],
        "source_window_id": window_id,
        "calibration_scenario_id": calibration_scenario_id,
        "window_start_date": spec["start_date"],
        "window_end_date": spec["end_date"],
        "selected_call_count": len(selected_calls),
        "selected_booking_boxes": sum(
            int(row["synthetic_export_boxes"]) for row in selected_calls
        ),
        "adapter_protocol_version": adapter_audit[
            "adapter_protocol_version"
        ],
        **source,
    }
    return case, metadata

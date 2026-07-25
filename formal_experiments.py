"""Frozen instance bundles and source contracts for publication experiments."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

from config import (
    FORMAL_PUBLIC_CALIBRATION_SCENARIOS,
    FORMAL_PUBLIC_TEMPORAL_WINDOWS,
    FORMAL_PUBLIC_WINDOWS,
    FORMAL_TIME_BUDGETS_SECONDS,
)
from scripts.run_portmis_end_to_end import (
    build_portmis_rolling_case,
    select_calibrated_window,
)


INSTANCE_BUNDLE_SCHEMA = "rolling-instance-bundle-v1"
INSTANCE_PROTOCOL = "rolling-formal-instances-v1"
PORTMIS_SOURCE_CONTRACT = "portmis-fixed-source-snapshot-v2"
PORTMIS_PORTAL_ACQUISITION_MODE = "official_provider_portal_export"
PORTMIS_REQUIRED_EVIDENCE_FILES = {
    "official_openapi_catalog.json",
    "official_file_catalog.json",
    "official_openapi_page.html",
    "official_file_page.html",
    "official_portal_view.xml",
}
PORTMIS_REQUIRED_UNOBSERVED_FIELDS = {
    "per_call_export_box_volume",
    "per_container_discharge_port",
    "container_size_and_height",
    "historical_booking_forecasts",
    "yard_inventory_and_bay_layout",
    "legacy_yard_allocation",
}


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


def _verify_sha256_declarations(
    base_dir: Path,
    declarations: dict,
    *,
    label: str,
) -> dict[str, str]:
    verified: dict[str, str] = {}
    for name, declaration in declarations.items():
        path = base_dir / name
        if not path.exists():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != declaration.get("sha256"):
            raise ValueError(f"{label} hash mismatch: {path}")
        declared_bytes = declaration.get("bytes")
        if (
            declared_bytes is not None
            and int(declared_bytes) != path.stat().st_size
        ):
            raise ValueError(f"{label} byte count mismatch: {path}")
        verified[name] = actual
    return verified


def _catalog_is_unrestricted(catalog: dict) -> bool:
    license_text = str(catalog.get("license", "")).strip()
    return (
        "제한 없음" in license_text
        or license_text.lower() in {"no restrictions", "unrestricted"}
    )


def _extract_catalog_content_url(page: str) -> str:
    match = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', page)
    if not match:
        raise ValueError(
            "official fileData evidence does not declare contentUrl"
        )
    return html.unescape(match.group(1))


def _verify_publication_portal_contract(
    source: dict,
    source_manifest_path: Path,
) -> dict[str, str]:
    """Validate official provenance rather than trusting a Boolean flag."""
    if source.get("schema") != PORTMIS_SOURCE_CONTRACT:
        raise ValueError(
            "publication-ready PORT-MIS manifest has an unsupported schema"
        )
    if source.get("acquisition_mode") != PORTMIS_PORTAL_ACQUISITION_MODE:
        raise ValueError(
            "publication-ready PORT-MIS source must use the frozen official "
            "provider portal export contract"
        )
    missing = [
        field
        for field in (
            "official_data_page",
            "official_file_page",
            "extraction_method",
            "portal_contract",
            "query",
            "raw_files",
            "standardized_files",
            "official_metadata_files",
            "source_snapshot_sha256",
            "source_revision_policy",
            "data_coverage",
        )
        if not source.get(field)
    ]
    if missing:
        raise ValueError(
            "publication-ready PORT-MIS manifest is incomplete: "
            + ", ".join(missing)
        )

    evidence = source["official_metadata_files"]
    missing_evidence = PORTMIS_REQUIRED_EVIDENCE_FILES - set(evidence)
    if missing_evidence:
        raise ValueError(
            "publication-ready PORT-MIS evidence is incomplete: "
            + ", ".join(sorted(missing_evidence))
        )
    verified_evidence = _verify_sha256_declarations(
        source_manifest_path.parent,
        evidence,
        label="official metadata",
    )
    openapi_catalog = _read_json(
        source_manifest_path.parent / "official_openapi_catalog.json"
    )
    file_catalog = _read_json(
        source_manifest_path.parent / "official_file_catalog.json"
    )
    if openapi_catalog.get("url") != source["official_data_page"]:
        raise ValueError("official OpenAPI catalogue identity mismatch")
    if file_catalog.get("url") != source["official_file_page"]:
        raise ValueError("official fileData catalogue identity mismatch")
    for catalog in (openapi_catalog, file_catalog):
        if not _catalog_is_unrestricted(catalog):
            raise ValueError(
                "official catalogue does not declare unrestricted use"
            )
        if (catalog.get("creator") or {}).get("name") != "해양수산부":
            raise ValueError("official catalogue provider identity mismatch")

    portal = source["portal_contract"]
    if (
        portal.get("method") != "POST"
        or portal.get("documented_openapi_used") is not False
        or portal.get("transport_endpoint_status")
        != "bound_to_archived_official_provider_ui"
    ):
        raise ValueError("PORT-MIS portal transport contract is incomplete")
    content_url = str(portal.get("official_content_url", ""))
    transport_url = str(portal.get("transport_url", ""))
    if not content_url.startswith("https://new.portmis.go.kr/portmis/"):
        raise ValueError("PORT-MIS official content URL is outside provider")
    if not transport_url.startswith("https://new.portmis.go.kr/portmis/"):
        raise ValueError("PORT-MIS transport URL is outside provider")

    file_page = (
        source_manifest_path.parent / "official_file_page.html"
    ).read_text(encoding="utf-8")
    declared_content_url = _extract_catalog_content_url(file_page)
    if urllib.parse.unquote(declared_content_url) != urllib.parse.unquote(
        content_url
    ):
        raise ValueError("fileData contentUrl/portal contract mismatch")
    portal_ui = (
        source_manifest_path.parent / "official_portal_view.xml"
    ).read_text(encoding="utf-8")
    transport_path = urllib.parse.urlparse(transport_url).path.replace(
        "/portmis", "", 1
    )
    if transport_path not in portal_ui:
        raise ValueError("PORT-MIS UI/transport endpoint mismatch")
    openapi_page = (
        source_manifest_path.parent / "official_openapi_page.html"
    ).read_text(encoding="utf-8")
    if (
        '"name":"serviceKey"' not in openapi_page
        or '"required":true' not in openapi_page
    ):
        raise ValueError("documented OpenAPI service-key evidence is missing")

    query = source.get("query") or {}
    missing_query = [
        field
        for field in ("port_code", "start_date", "end_date")
        if not query.get(field)
    ]
    if missing_query:
        raise ValueError(
            "PORT-MIS query scope is incomplete: "
            + ", ".join(missing_query)
        )
    directions = query.get("directions") or {}
    if set(directions) != {"inbound", "outbound"}:
        raise ValueError("PORT-MIS request declarations are incomplete")
    if {
        declaration.get("direction")
        for declaration in source["raw_files"].values()
    } != set(directions):
        raise ValueError("PORT-MIS raw direction coverage is incomplete")
    for name, declaration in source["raw_files"].items():
        direction = declaration.get("direction")
        request = directions.get(direction) or {}
        if declaration.get("request_body_sha256") != request.get("body_sha256"):
            raise ValueError(f"raw/request identity mismatch: {name}")
        if int(declaration.get("rows", -1)) < 0:
            raise ValueError(f"raw row count is invalid: {name}")
    snapshot_payload = {
        "requests": directions,
        "raw_files": source["raw_files"],
    }
    expected_snapshot = hashlib.sha256(
        json.dumps(
            snapshot_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if expected_snapshot != source["source_snapshot_sha256"]:
        raise ValueError("PORT-MIS source snapshot identity mismatch")

    revision = source["source_revision_policy"]
    if not all(
        revision.get(field) is True
        for field in (
            "archived_bytes_are_immutable",
            "provider_corrections_require_new_snapshot",
            "live_refetch_hash_is_not_a_reproducibility_requirement",
        )
    ):
        raise ValueError("PORT-MIS source revision policy is incomplete")
    coverage = source["data_coverage"]
    if not PORTMIS_REQUIRED_UNOBSERVED_FIELDS.issubset(
        set(coverage.get("not_observed_from_portmis") or ())
    ):
        raise ValueError("PORT-MIS semi-synthetic data boundary is incomplete")
    if not coverage.get("observed_from_portmis") or not coverage.get("treatment"):
        raise ValueError("PORT-MIS data lineage declaration is incomplete")
    return verified_evidence


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
    verified_outputs = _verify_sha256_declarations(
        calibration_dir,
        calibration_manifest.get("outputs", {}),
        label="calibration",
    )
    calibration_audit_path = calibration_dir / "audit.json"
    calibration_audit = _read_json(calibration_audit_path)
    if calibration_audit.get("calibration_status") != "PASS":
        raise ValueError("PORT-MIS demand calibration audit did not pass")

    if source_manifest is not None:
        source_manifest_path = Path(source_manifest)
    else:
        declared_source_dir = (
            calibration_manifest.get("source") or {}
        ).get("pilot_directory")
        declared_candidate = (
            Path(declared_source_dir) / "manifest.json"
            if declared_source_dir
            else None
        )
        source_manifest_path = (
            declared_candidate
            if declared_candidate is not None and declared_candidate.is_file()
            else calibration_dir.parent / "manifest.json"
        )
    source = _read_json(source_manifest_path)
    verified_raw = _verify_sha256_declarations(
        source_manifest_path.parent,
        source.get("raw_files", {}),
        label="raw source",
    )

    publication_ready = bool(source.get("publication_ready", False)) and not bool(
        source.get("pilot_only_undocumented_endpoint", False)
    )
    verified_evidence: dict[str, str] = {}
    verified_standardized: dict[str, str] = {}
    if publication_ready:
        verified_evidence = _verify_publication_portal_contract(
            source,
            source_manifest_path,
        )
        verified_standardized = _verify_sha256_declarations(
            source_manifest_path.parent,
            source["standardized_files"],
            label="standardized source",
        )
        calibration_source = calibration_manifest.get("source") or {}
        expected_links = {
            "primary_cluster_calls.csv": calibration_source.get(
                "primary_cluster_calls_sha256"
            ),
            "audit.json": calibration_source.get("pilot_audit_sha256"),
        }
        broken_links = [
            name
            for name, expected in expected_links.items()
            if not expected or verified_standardized.get(name) != expected
        ]
        if broken_links:
            raise ValueError(
                "calibration/source lineage mismatch: "
                + ", ".join(broken_links)
            )
    if require_publication_ready and not publication_ready:
        raise ValueError(
            "PORT-MIS source is verified but provisional: formal public-data "
            "runs require a fully verified official-provider source contract"
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
        "source_raw_snapshot_sha256": source.get("source_snapshot_sha256"),
        "source_publication_ready": publication_ready,
        "pilot_only_undocumented_endpoint": bool(
            source.get("pilot_only_undocumented_endpoint", False)
        ),
        "verified_outputs": verified_outputs,
        "verified_raw_files": verified_raw,
        "verified_standardized_files": verified_standardized,
        "verified_official_metadata": verified_evidence,
        "calibration_protocol": calibration_audit.get("protocol_version"),
        "source_acquisition_mode": source.get("acquisition_mode"),
        "source_data_coverage": source.get("data_coverage", {}),
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
    public_specs = {
        **FORMAL_PUBLIC_WINDOWS,
        **FORMAL_PUBLIC_TEMPORAL_WINDOWS,
    }
    if window_id not in public_specs:
        raise ValueError(
            f"window_id must be one of {tuple(public_specs)}"
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
    if calibration_scenario_id not in FORMAL_PUBLIC_CALIBRATION_SCENARIOS:
        raise ValueError(
            "unknown frozen public calibration scenario: "
            f"{calibration_scenario_id}"
        )
    expected_assumptions = FORMAL_PUBLIC_CALIBRATION_SCENARIOS[
        calibration_scenario_id
    ]
    actual_assumptions = source.get("calibration_scenario_assumptions") or {}
    if actual_assumptions != expected_assumptions:
        differing = sorted(
            key
            for key in set(actual_assumptions) | set(expected_assumptions)
            if actual_assumptions.get(key) != expected_assumptions.get(key)
        )
        raise ValueError(
            "calibration scenario label/assumption mismatch for "
            f"{calibration_scenario_id}: {', '.join(differing)}"
        )
    calls = _read_csv(calibration_dir / "calibrated_call_demand.csv")
    groups = _read_csv(calibration_dir / "calibrated_group_demand.csv")
    spec = public_specs[window_id]
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
        "public_panel_role": (
            "temporal_robustness"
            if window_id in FORMAL_PUBLIC_TEMPORAL_WINDOWS
            else "primary_scale"
        ),
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
        "public_panel_role": case["public_panel_role"],
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

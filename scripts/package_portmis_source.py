"""Build a deterministic publication archive for one verified PORT-MIS source."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formal_experiments import sha256_file, verify_portmis_source  # noqa: E402


ARCHIVE_SCHEMA = "portmis-publication-archive-v1"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _source_member_names(manifest: dict) -> set[str]:
    names = {"manifest.json", "report.md"}
    for field in (
        "raw_files",
        "standardized_files",
        "official_metadata_files",
    ):
        names.update(manifest.get(field, {}))
    return names


def _calibration_member_names(manifest: dict) -> set[str]:
    return {"manifest.json", *manifest.get("outputs", {})}


def _member_declarations(
    source_dir: Path,
    calibration_dir: Path,
    source_manifest: dict,
    calibration_manifest: dict,
) -> tuple[dict[str, dict[str, object]], dict[str, bytes]]:
    payloads: dict[str, bytes] = {}
    for name in sorted(_source_member_names(source_manifest)):
        path = source_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        payloads[f"source/{name}"] = path.read_bytes()
    for name in sorted(_calibration_member_names(calibration_manifest)):
        path = calibration_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        payloads[f"calibration/{name}"] = path.read_bytes()
    declarations = {
        name: {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
        for name, raw in sorted(payloads.items())
    }
    return declarations, payloads


def _write_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    raw: bytes,
) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(
        info,
        raw,
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


def package_snapshot(
    *,
    source_dir: str | Path,
    calibration_dir: str | Path | None = None,
    output: str | Path,
) -> dict[str, object]:
    """Verify and package one source/calibration chain without live re-query."""
    source_dir = Path(source_dir).resolve()
    calibration_dir = (
        Path(calibration_dir).resolve()
        if calibration_dir is not None
        else source_dir / "calibrated_demand_v1"
    )
    output = Path(output).resolve()
    source_manifest_path = source_dir / "manifest.json"
    calibration_manifest_path = calibration_dir / "manifest.json"
    verification = verify_portmis_source(
        calibration_dir,
        source_manifest=source_manifest_path,
        require_publication_ready=True,
    )
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8-sig")
    )
    calibration_manifest = json.loads(
        calibration_manifest_path.read_text(encoding="utf-8-sig")
    )
    members, payloads = _member_declarations(
        source_dir,
        calibration_dir,
        source_manifest,
        calibration_manifest,
    )
    archive_manifest = {
        "archive_schema": ARCHIVE_SCHEMA,
        "source_contract": verification["source_contract"],
        "source_raw_snapshot_sha256": verification[
            "source_raw_snapshot_sha256"
        ],
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "calibration_manifest_sha256": sha256_file(calibration_manifest_path),
        "source_period": [
            source_manifest["query"]["start_date"],
            source_manifest["query"]["end_date"],
        ],
        "members": members,
    }
    manifest_raw = _json_bytes(archive_manifest)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        _write_zip_member(
            archive,
            "publication_archive_manifest.json",
            manifest_raw,
        )
        for name, raw in sorted(payloads.items()):
            _write_zip_member(archive, name, raw)
    os.replace(temporary, output)
    return {
        "archive_schema": ARCHIVE_SCHEMA,
        "archive_path": output.as_posix(),
        "archive_sha256": sha256_file(output),
        "archive_bytes": output.stat().st_size,
        "member_count": len(payloads) + 1,
        "source_period": archive_manifest["source_period"],
        "source_manifest_sha256": archive_manifest[
            "source_manifest_sha256"
        ],
        "calibration_manifest_sha256": archive_manifest[
            "calibration_manifest_sha256"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--calibration-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = package_snapshot(
        source_dir=args.source_dir,
        calibration_dir=args.calibration_dir,
        output=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

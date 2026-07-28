"""Build the V2 Yangshan calibration layer from observations only.

Calibration snapshots: 2026-05-08 and 2026-05-19.
Held-out temporal validation snapshot: 2026-05-25.

Voyage predictions and import-discharge files are intentionally never read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd


SNAPSHOTS = ("0508", "0519", "0525")
CALIBRATION_SNAPSHOTS = ("0508", "0519")
VALIDATION_SNAPSHOT = "0525"
HEIGHT_MAP = {"HQ": "HIGH", "PQ": "STD", "MQ": "STD"}
EXPORT_FILE_RE = re.compile(r"container_info_(\d+)\.parquet$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_raw_dir(data_root: Path, snapshot: str) -> Path:
    base = data_root / f"pro_test_data_{snapshot}"
    candidates = [
        child
        for child in base.iterdir()
        if child.is_dir() and (child / "bay_slots_detail.parquet").exists()
        and any(child.glob("container_info_*.parquet"))
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"Cannot resolve canonical raw directory for {snapshot}")
    return candidates[0]


def yard_function_path(
    data_root: Path, snapshot: str, source_dir: Path
) -> Path:
    for base in (source_dir, data_root / f"pro_test_data_{snapshot}"):
        for path in base.glob("*.xlsx"):
            try:
                columns = set(pd.read_excel(path, nrows=1).columns)
            except Exception:
                continue
            if {"area_no", "cntr_type", "load_campacity"} <= columns:
                return path
    raise RuntimeError(f"Cannot resolve yard-function workbook for {snapshot}")


def normalized_area(value: object) -> str:
    text = str(value).strip().upper()
    return text[:-2] if text.endswith(".0") else text


def export_yard_areas(path: Path) -> set[str]:
    functions = pd.read_excel(path)
    functions["normalized_area"] = functions["area_no"].map(normalized_area)
    has_of = functions["cntr_type"].astype(str).map(
        lambda value: "OF" in {
            token.strip() for token in value.upper().split(",")
        }
    )
    return set(functions.loc[has_of, "normalized_area"])


def normalized_container_id(value: object) -> str | None:
    if pd.isna(value):
        return None
    return str(int(float(value)))


def load_snapshot(
    data_root: Path, snapshot: str
) -> tuple[pd.DataFrame, dict[str, object], list[Path]]:
    source_dir = canonical_raw_dir(data_root, snapshot)
    yard_path = source_dir / "bay_slots_detail.parquet"
    function_path = yard_function_path(data_root, snapshot, source_dir)
    eligible_areas = export_yard_areas(function_path)
    yard_slots = pd.read_parquet(yard_path)
    yard_slots["normalized_area"] = yard_slots["YAA_AREANO"].map(
        normalized_area
    )
    export_yard_slots = yard_slots.loc[
        yard_slots["normalized_area"].isin(eligible_areas)
    ].copy()
    occupied = export_yard_slots.loc[
        (export_yard_slots["HAS_CONTAINER"] == 1)
        & export_yard_slots["IYC_CNTRID"].notna()
    ].copy()
    occupied["container_id"] = occupied["IYC_CNTRID"].map(normalized_container_id)
    occupied = occupied.drop_duplicates("container_id", keep="first")
    occupied = occupied.loc[occupied["IYC_EVOY_ID"].notna()].copy()
    occupied["evidence_state"] = "yard_observed"
    occupied["state_priority"] = 1

    source_paths = [yard_path, function_path]
    documents = []
    for path in sorted(source_dir.glob("container_info_*.parquet")):
        if not EXPORT_FILE_RE.fullmatch(path.name):
            continue
        frame = pd.read_parquet(path).copy()
        frame["container_id"] = frame["IYC_CNTRID"].map(normalized_container_id)
        frame["evidence_state"] = "declared_not_in_yard"
        frame["state_priority"] = 0
        documents.append(frame)
        source_paths.append(path)
    docs = pd.concat(documents, ignore_index=True)
    docs = docs.loc[docs["IYC_EVOY_ID"].notna()].copy()

    evidence = pd.concat([occupied, docs], ignore_index=True, sort=False)
    evidence["snapshot"] = snapshot
    evidence = (
        evidence.sort_values("state_priority")
        .drop_duplicates("container_id", keep="last")
        .copy()
    )
    evidence["size_ft"] = pd.to_numeric(
        evidence["IYC_CSZ_CSIZECD"], errors="coerce"
    ).astype("Int64")
    evidence["height_class"] = evidence["IYC_CHEIGHTCD"].map(HEIGHT_MAP)
    evidence["pod"] = evidence["IYC_POT_UNLDPORT"].astype("string")
    evidence = evidence.loc[
        evidence["size_ft"].isin([20, 40])
        & evidence["height_class"].notna()
        & evidence["pod"].notna()
        & evidence["IYC_EVOY_ID"].notna()
        & evidence["pod"].ne("CNSHA")
    ].copy()

    yard_summary = {
        "snapshot": snapshot,
        "yard_scope": "areas whose function list contains OF",
        "of_areas_listed": len(eligible_areas),
        "of_areas_with_slots": int(
            export_yard_slots["normalized_area"].nunique()
        ),
        "of_areas_without_slots": len(
            eligible_areas - set(yard_slots["normalized_area"])
        ),
        "slot_rows": len(export_yard_slots),
        "areas": int(export_yard_slots["normalized_area"].nunique()),
        "bays": int(export_yard_slots["YBY_BAYID"].nunique()),
        "tiers": int(
            pd.to_numeric(
                export_yard_slots["YST_TIERNO"], errors="coerce"
            ).max()
        ),
        "occupied_slot_rows": int(
            (
                (export_yard_slots["HAS_CONTAINER"] == 1)
                & export_yard_slots["IYC_CNTRID"].notna()
            ).sum()
        ),
        "occupied_slot_share": float(
            (
                (export_yard_slots["HAS_CONTAINER"] == 1)
                & export_yard_slots["IYC_CNTRID"].notna()
            ).mean()
        ),
        "unique_export_yard_containers": int(occupied["container_id"].nunique()),
        "declared_not_in_yard_containers": int(docs["container_id"].nunique()),
        "model_compatible_export_union": len(evidence),
        "direction_rule": "nonmissing IYC_EVOY_ID",
        "home_port_pod_excluded": "CNSHA",
    }
    return evidence, yard_summary, source_paths


def joint_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    result = (
        frame.groupby(["pod", "size_ft", "height_class"])
        .size()
        .rename("observed_containers")
        .reset_index()
    )
    result["probability"] = result["observed_containers"] / result[
        "observed_containers"
    ].sum()
    return result.sort_values(
        ["probability", "pod", "size_ft", "height_class"],
        ascending=[False, True, True, True],
    )


def categorical_tv(
    calibration: pd.DataFrame, validation: pd.DataFrame, columns: list[str]
) -> float:
    left = calibration.groupby(columns).size()
    right = validation.groupby(columns).size()
    index = left.index.union(right.index)
    left = left.reindex(index, fill_value=0) / left.sum()
    right = right.reindex(index, fill_value=0) / right.sum()
    return float(0.5 * (left - right).abs().sum())


def build(data_root: Path, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    yard_rows = []
    source_rows = []
    for snapshot in SNAPSHOTS:
        frame, yard_summary, sources = load_snapshot(data_root, snapshot)
        frames[snapshot] = frame
        yard_rows.append(yard_summary)
        role = "calibration" if snapshot in CALIBRATION_SNAPSHOTS else "validation"
        for path in sources:
            source_rows.append(
                {
                    "snapshot": snapshot,
                    "role": role,
                    "path": path.relative_to(data_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

    calibration = pd.concat(
        [frames[snapshot] for snapshot in CALIBRATION_SNAPSHOTS],
        ignore_index=True,
    )
    calibration["snapshot_order"] = pd.to_numeric(calibration["snapshot"])
    calibration = (
        calibration.sort_values(["snapshot_order", "state_priority"])
        .drop_duplicates("container_id", keep="last")
        .copy()
    )
    validation = frames[VALIDATION_SNAPSHOT]
    distribution = joint_distribution(calibration)
    validation_distribution = joint_distribution(validation)
    voyage_profiles = (
        calibration.groupby(
            ["IYC_EVOY_ID", "pod", "size_ft", "height_class"]
        )
        .size()
        .rename("observed_containers")
        .reset_index()
    )
    voyage_totals = (
        calibration.groupby("IYC_EVOY_ID")
        .agg(
            voyage_observed_boxes=("container_id", "size"),
            voyage_observed_pods=("pod", "nunique"),
        )
        .reset_index()
    )
    voyage_profiles = voyage_profiles.merge(
        voyage_totals, on="IYC_EVOY_ID", validate="many_to_one"
    )
    voyage_profiles["within_voyage_probability"] = (
        voyage_profiles["observed_containers"]
        / voyage_profiles["voyage_observed_boxes"]
    )

    distribution.to_csv(
        output_root / "observed_joint_distribution.csv",
        index=False,
        encoding="utf-8-sig",
    )
    validation_distribution.to_csv(
        output_root / "heldout_joint_distribution.csv",
        index=False,
        encoding="utf-8-sig",
    )
    voyage_profiles.to_csv(
        output_root / "observed_voyage_group_profiles.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(yard_rows).to_csv(
        output_root / "yard_calibration.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(source_rows).to_csv(
        output_root / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )

    validation_metrics = {
        "validation_snapshot": VALIDATION_SNAPSHOT,
        "calibration_unique_containers": len(calibration),
        "validation_unique_containers": len(validation),
        "calibration_pods": int(calibration["pod"].nunique()),
        "validation_pods": int(validation["pod"].nunique()),
        "pod_total_variation_distance": categorical_tv(
            calibration, validation, ["pod"]
        ),
        "size_total_variation_distance": categorical_tv(
            calibration, validation, ["size_ft"]
        ),
        "height_total_variation_distance": categorical_tv(
            calibration, validation, ["height_class"]
        ),
        "joint_total_variation_distance": categorical_tv(
            calibration, validation, ["pod", "size_ft", "height_class"]
        ),
        "validation_pod_coverage_by_calibration": float(
            validation["pod"].isin(set(calibration["pod"])).mean()
        ),
    }
    (output_root / "temporal_validation.json").write_text(
        json.dumps(validation_metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    outputs = {}
    for name in (
        "observed_joint_distribution.csv",
        "heldout_joint_distribution.csv",
        "observed_voyage_group_profiles.csv",
        "yard_calibration.csv",
        "source_manifest.csv",
        "temporal_validation.json",
    ):
        path = output_root / name
        outputs[name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    manifest = {
        "protocol_version": "pnc-yangshan-observed-v2",
        "created_by": "scripts/build_yangshan_observed_calibration.py",
        "vessel_layer": {
            "primary_source": "PNC operator berth schedule",
            "supplementary_validation": "PORT-MIS",
            "status": "built separately",
        },
        "yangshan_layer": {
            "calibration_snapshots": list(CALIBRATION_SNAPSHOTS),
            "held_out_validation_snapshot": VALIDATION_SNAPSHOT,
            "evidence": [
                "deduplicated export-voyage yard containers",
                "declared export containers not yet in yard",
            ],
            "explicitly_excluded": [
                "voyage predictions",
                "prediction workbooks",
                "import-discharge records",
                "algorithm inputs and outputs",
                "45-foot containers",
            ],
            "height_mapping": HEIGHT_MAP,
        },
        "model_boundary": {
            "sizes_ft": [20, 40],
            "height_classes": ["STD", "HIGH"],
            "group_attributes": ["pod", "size_ft", "height_class"],
            "mathematical_model_changed": False,
            "algorithms_changed": False,
        },
        "temporal_validation": validation_metrics,
        "outputs": outputs,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data_analysis"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/yangshan_observed_calibration"
        ),
    )
    args = parser.parse_args()
    print(json.dumps(build(args.data_root, args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

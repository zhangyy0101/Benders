"""Audit the Yangshan snapshots without treating algorithm artifacts as evidence.

The audit keeps three evidence layers separate:

1. yard observations: containers physically present in a yard snapshot;
2. document records: declared export containers not yet in the yard;
3. voyage predictions: predicted totals for the complete voyage population.

Outputs are aggregate-only and contain no container numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


SNAPSHOT_RE = re.compile(r"pro_test_data_(\d{4})$")
VOYAGE_FILE_RE = re.compile(r"container_info_(\d+)\.parquet$")
IMPORT_FILE_RE = re.compile(r"container_info_import(?:_voy)?_(\d+)\.parquet$")
ALGORITHM_MARKERS = (
    "_result.parquet",
    "_plan.parquet",
    "corrected_large_plan.parquet",
    "previous_large_plan_result.parquet",
    "input_data.json",
    "run_flat_full_yard_plan.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm_id(value: object) -> str | None:
    if pd.isna(value):
        return None
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


def raw_dir(snapshot_dir: Path) -> Path:
    candidates = [
        child
        for child in snapshot_dir.iterdir()
        if child.is_dir() and (child / "voyage_predict.json").exists()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one canonical raw directory in {snapshot_dir}, found {candidates}"
        )
    return candidates[0]


def value_counts(
    frame: pd.DataFrame, column: str, snapshot: str, source: str
) -> list[dict[str, object]]:
    if column not in frame:
        return []
    values = frame[column].fillna("<MISSING>").astype(str).str.strip()
    counts = values.value_counts(dropna=False)
    total = int(counts.sum())
    return [
        {
            "snapshot": snapshot,
            "source": source,
            "attribute": column,
            "value": value,
            "count": int(count),
            "share": float(count / total) if total else None,
        }
        for value, count in counts.items()
    ]


def prediction_total(record: dict[str, object], allowed_sizes: set[str] | None = None) -> int:
    total = 0
    for size, detail in record.get("cntr_volume", {}).items():
        if allowed_sizes is None or str(size) in allowed_sizes:
            total += int(detail.get("total_volume", 0))
    return total


def classify_file(relative: str) -> tuple[str, bool]:
    name = Path(relative).name
    lowered = relative.lower()
    if any(marker in name for marker in ALGORITHM_MARKERS):
        return "algorithm_artifact", True
    if not lowered.startswith("pro_test_data_"):
        return "algorithm_or_derived_directory", True
    if name.startswith("bay_slots_detail"):
        return "yard_snapshot", False
    if VOYAGE_FILE_RE.match(name):
        return "declared_export_documents", False
    if IMPORT_FILE_RE.match(name):
        return "import_discharge_records", False
    if name.startswith(("his_data_", "predict_data_")) or name == "voyage_predict.json":
        return "voyage_prediction", False
    if name == "vessel_berth_info.csv":
        return "vessel_schedule_context", False
    if name == "tops_plan_info.parquet":
        return "operational_yard_plan", False
    if name in {"箱区功能.xlsx", "适放箱区_泊位距离矩阵.xlsx", "n_usefg_areas.txt"}:
        return "yard_configuration", False
    if name.endswith(".docx"):
        return "documentation", False
    return "unclassified", False


def audit(data_root: Path, output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(
        path
        for path in data_root.iterdir()
        if path.is_dir() and SNAPSHOT_RE.match(path.name)
    )

    canonical_dirs = [raw_dir(path) for path in snapshots]
    file_rows: list[dict[str, object]] = []
    for path in sorted(item for item in data_root.rglob("*") if item.is_file()):
        relative = path.relative_to(data_root).as_posix()
        category, excluded = classify_file(relative)
        file_rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "category": category,
                "excluded_from_empirical_evidence": excluded,
                "selected_canonical_source": any(
                    path.is_relative_to(directory) for directory in canonical_dirs
                ),
            }
        )
    file_inventory = pd.DataFrame(file_rows)
    file_inventory["duplicate_content"] = file_inventory.duplicated("sha256", keep=False)
    file_inventory.to_csv(output_root / "file_inventory.csv", index=False, encoding="utf-8-sig")

    snapshot_rows: list[dict[str, object]] = []
    voyage_rows: list[dict[str, object]] = []
    distribution_rows: list[dict[str, object]] = []
    prediction_distribution_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    all_yard: list[pd.DataFrame] = []
    all_yard_export: list[pd.DataFrame] = []
    all_docs: list[pd.DataFrame] = []

    for snapshot_dir in snapshots:
        snapshot = snapshot_dir.name.removeprefix("pro_test_data_")
        source_dir = raw_dir(snapshot_dir)
        yard = pd.read_parquet(source_dir / "bay_slots_detail.parquet")
        occupied_slots = yard.loc[
            (yard["HAS_CONTAINER"] == 1) & yard["IYC_CNTRID"].notna()
        ].copy()
        occupied_slots["container_id"] = occupied_slots["IYC_CNTRID"].map(norm_id)
        # A 40/45-foot container may occupy two slot rows. Container evidence must
        # therefore be deduplicated even though slot occupancy retains both rows.
        occupied = occupied_slots.drop_duplicates("container_id", keep="first").copy()
        occupied["snapshot"] = snapshot
        occupied["voyage_id"] = occupied["IYC_EVOY_ID"].map(norm_id)
        occupied_export = occupied.loc[occupied["voyage_id"].notna()].copy()
        all_yard.append(occupied)
        all_yard_export.append(occupied_export)

        doc_frames: list[pd.DataFrame] = []
        import_frames: list[pd.DataFrame] = []
        for path in sorted(source_dir.glob("container_info_*.parquet")):
            export_match = VOYAGE_FILE_RE.match(path.name)
            import_match = IMPORT_FILE_RE.match(path.name)
            frame = pd.read_parquet(path)
            if export_match:
                frame = frame.copy()
                frame["snapshot"] = snapshot
                frame["voyage_id"] = export_match.group(1)
                frame["container_id"] = frame["IYC_CNTRID"].map(norm_id)
                doc_frames.append(frame)
            elif import_match:
                import_frames.append(frame)
        docs = pd.concat(doc_frames, ignore_index=True) if doc_frames else pd.DataFrame()
        imports = (
            pd.concat(import_frames, ignore_index=True) if import_frames else pd.DataFrame()
        )
        if not docs.empty:
            all_docs.append(docs)

        predictions = json.loads(
            (source_dir / "voyage_predict.json").read_text(encoding="utf-8")
        )
        for voyage, prediction in predictions.items():
            for size, detail in prediction.get("cntr_volume", {}).items():
                for pod, count in detail.get("detail_info", {}).items():
                    prediction_distribution_rows.append(
                        {
                            "snapshot": snapshot,
                            "voyage_id": voyage,
                            "size_ft": str(size),
                            "pod": pod,
                            "predicted_count": int(count),
                            "model_compatible_size": str(size) in {"20", "40"},
                        }
                    )
        workbook_checks = []
        for path in sorted(
            list(source_dir.glob("his_data_*.xlsx"))
            + list(source_dir.glob("predict_data_*.xlsx"))
        ):
            match = re.search(r"_(\d+)(?:_\d+)?\.xlsx$", path.name)
            if not match:
                continue
            voyage = match.group(1)
            workbook = pd.read_excel(path)
            workbook_sizes = {
                str(int(row["IYC_CSZ_CSIZECD"])): int(row["count"])
                for _, row in workbook.iterrows()
            }
            json_sizes = {
                str(size): int(detail.get("total_volume", 0))
                for size, detail in predictions.get(voyage, {})
                .get("cntr_volume", {})
                .items()
            }
            workbook_checks.append(workbook_sizes == json_sizes)
        berth = pd.read_csv(source_dir / "vessel_berth_info.csv")
        berth["voyage_id"] = berth["VOY_ID"].map(norm_id)
        berth = berth.drop_duplicates("voyage_id", keep="last").set_index("voyage_id")

        yard_ids = set(occupied["container_id"].dropna())
        doc_ids = set(docs["container_id"].dropna()) if not docs.empty else set()
        snapshot_rows.append(
            {
                "snapshot": snapshot,
                "raw_directory": source_dir.relative_to(data_root).as_posix(),
                "yard_slots": len(yard),
                "yard_areas": yard["YAA_AREANO"].nunique(dropna=True),
                "yard_bays": yard["YBY_BAYID"].nunique(dropna=True),
                "yard_slot_ids": yard["YST_SLOTNO"].nunique(dropna=True),
                "yard_max_tier": pd.to_numeric(
                    yard["YST_TIERNO"], errors="coerce"
                ).max(),
                "occupied_slot_rows": len(occupied_slots),
                "yard_occupied_slot_share": len(occupied_slots) / len(yard),
                "yard_unique_containers": occupied["container_id"].nunique(),
                "yard_export_unique_containers": occupied_export[
                    "container_id"
                ].nunique(),
                "slot_rows_per_container": (
                    len(occupied_slots) / occupied["container_id"].nunique()
                ),
                "yard_export_voyages": occupied["voyage_id"].nunique(dropna=True),
                "declared_export_files": len(doc_frames),
                "declared_export_records": len(docs),
                "declared_export_unique_containers": (
                    docs["container_id"].nunique() if not docs.empty else 0
                ),
                "import_files": len(import_frames),
                "import_records": len(imports),
                "prediction_voyages": len(predictions),
                "prediction_workbooks": len(workbook_checks),
                "prediction_workbooks_matching_json": sum(workbook_checks),
                "same_container_in_yard_and_documents": len(yard_ids & doc_ids),
                "yard_entry_time_min": occupied["IYC_INYTM"].min(),
                "yard_entry_time_max": occupied["IYC_INYTM"].max(),
            }
        )

        for source, frame in (
            ("yard_all_observed", occupied),
            ("yard_export_observed", occupied_export),
            ("declared_not_in_yard", docs),
        ):
            for column in (
                "IYC_CSZ_CSIZECD",
                "IYC_CHEIGHTCD",
                "IYC_POT_UNLDPORT",
                "IYC_CST_COPERCD",
                "IYC_CTYPECD",
                "IYC_STS_CSTATUSCD",
            ):
                distribution_rows.extend(value_counts(frame, column, snapshot, source))

        yard_by_voyage = occupied.groupby("voyage_id", dropna=True).size().to_dict()
        doc_by_voyage = (
            docs.groupby("voyage_id", dropna=True).size().to_dict()
            if not docs.empty
            else {}
        )
        yard_container_sets = {
            voyage: set(group["container_id"].dropna())
            for voyage, group in occupied.groupby("voyage_id", dropna=True)
        }
        doc_container_sets = (
            {
                voyage: set(group["container_id"].dropna())
                for voyage, group in docs.groupby("voyage_id", dropna=True)
            }
            if not docs.empty
            else {}
        )
        voyage_ids = sorted(set(yard_by_voyage) | set(doc_by_voyage) | set(predictions))
        for voyage in voyage_ids:
            pred = predictions.get(voyage)
            y_count = int(yard_by_voyage.get(voyage, 0))
            d_count = int(doc_by_voyage.get(voyage, 0))
            overlap = len(
                yard_container_sets.get(voyage, set())
                & doc_container_sets.get(voyage, set())
            )
            pred_all = prediction_total(pred) if pred else None
            pred_model = (
                prediction_total(pred, {"20", "40"}) if pred else None
            )
            berth_row = berth.loc[voyage] if voyage in berth.index else None
            vessel_label = None
            for frame in (docs, occupied):
                if "IYC_EVESVOYAGE" not in frame:
                    continue
                labels = frame.loc[
                    frame["voyage_id"] == voyage, "IYC_EVESVOYAGE"
                ].dropna()
                if not labels.empty:
                    vessel_label = str(labels.iloc[0])
                    break
            voyage_rows.append(
                {
                    "snapshot": snapshot,
                    "voyage_id": voyage,
                    "vessel_name_en": (
                        berth_row.get("VSL_ENNAME")
                        if berth_row is not None and "VSL_ENNAME" in berth.columns
                        else None
                    ),
                    "vessel_name_cn": (
                        berth_row.get("VSL_CNNAME")
                        if berth_row is not None and "VSL_CNNAME" in berth.columns
                        else None
                    ),
                    "vessel_voyage_label": vessel_label,
                    "berth_planned_at": (
                        berth_row.get("VBT_PBTHDT") if berth_row is not None else None
                    ),
                    "yard_observed": y_count,
                    "declared_not_in_yard": d_count,
                    "same_container_overlap": overlap,
                    "observed_union_lower_bound": y_count + d_count - overlap,
                    "predicted_total_all_sizes": pred_all,
                    "predicted_total_model_20_40": pred_model,
                    "prediction_includes_45ft": (
                        bool(
                            pred
                            and prediction_total(pred, {"45"}) > 0
                        )
                    ),
                    "has_yard": y_count > 0,
                    "has_documents": d_count > 0,
                    "has_prediction": pred is not None,
                    "declared_share_of_prediction_20_40": (
                        d_count / pred_model if pred_model and d_count else None
                    ),
                    "observed_lower_bound_share_of_prediction_20_40": (
                        (y_count + d_count - overlap) / pred_model
                        if pred_model and (y_count or d_count)
                        else None
                    ),
                }
            )

    yard_all = pd.concat(all_yard, ignore_index=True)
    yard_export_all = pd.concat(all_yard_export, ignore_index=True)
    docs_all = pd.concat(all_docs, ignore_index=True)
    yard_states = yard_all.groupby("container_id")["snapshot"].agg(list)
    doc_states = docs_all.groupby("container_id")["snapshot"].agg(list)
    for container_id in sorted(set(yard_states.index) & set(doc_states.index)):
        doc_snaps = sorted(doc_states[container_id])
        yard_snaps = sorted(yard_states[container_id])
        transition_rows.append(
            {
                "container_id_hash": hashlib.sha256(
                    container_id.encode("utf-8")
                ).hexdigest(),
                "document_snapshots": "|".join(doc_snaps),
                "yard_snapshots": "|".join(yard_snaps),
                "document_before_yard": min(doc_snaps) < max(yard_snaps),
            }
        )

    pd.DataFrame(snapshot_rows).to_csv(
        output_root / "snapshot_summary.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(voyage_rows).to_csv(
        output_root / "voyage_coverage.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(distribution_rows).to_csv(
        output_root / "attribute_distributions.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(prediction_distribution_rows).to_csv(
        output_root / "prediction_pod_distributions.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(transition_rows).to_csv(
        output_root / "cross_snapshot_transitions.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # Pooled export observations use the latest observed state for each container.
    # A yard observation wins over a document record within the same snapshot.
    pooled_yard = yard_export_all.copy()
    pooled_yard["evidence_state"] = "yard_observed"
    pooled_yard["state_priority"] = 1
    pooled_docs = docs_all.copy()
    pooled_docs["evidence_state"] = "declared_not_in_yard"
    pooled_docs["state_priority"] = 0
    pooled = pd.concat([pooled_yard, pooled_docs], ignore_index=True, sort=False)
    pooled["snapshot_order"] = pd.to_numeric(pooled["snapshot"], errors="coerce")
    pooled = (
        pooled.sort_values(["snapshot_order", "state_priority"])
        .drop_duplicates("container_id", keep="last")
        .copy()
    )
    pooled["size_ft"] = pd.to_numeric(
        pooled["IYC_CSZ_CSIZECD"], errors="coerce"
    ).astype("Int64")
    pooled["height_class"] = pooled["IYC_CHEIGHTCD"].map(
        {"HQ": "HIGH", "PQ": "STD", "MQ": "STD"}
    )
    pooled["pod"] = pooled["IYC_POT_UNLDPORT"].astype("string")
    model_pooled = pooled.loc[
        pooled["size_ft"].isin([20, 40])
        & pooled["height_class"].notna()
        & pooled["pod"].notna()
    ]
    pooled_groups = (
        model_pooled.groupby(
            ["pod", "size_ft", "height_class"], dropna=False
        )
        .size()
        .rename("observed_unique_containers")
        .reset_index()
    )
    pooled_groups["share"] = (
        pooled_groups["observed_unique_containers"]
        / pooled_groups["observed_unique_containers"].sum()
    )
    pooled_groups.to_csv(
        output_root / "model_compatible_observed_groups.csv",
        index=False,
        encoding="utf-8-sig",
    )

    voyage_frame = pd.DataFrame(voyage_rows)
    comparable = voyage_frame.loc[
        voyage_frame["has_prediction"]
        & (voyage_frame["observed_union_lower_bound"] > 0)
    ]
    duplicate_groups = (
        file_inventory.loc[file_inventory["duplicate_content"]]
        .groupby("sha256")
        .size()
        .sort_values(ascending=False)
    )
    summary = {
        "snapshots": [path.name for path in snapshots],
        "snapshot_count": len(snapshots),
        "inventory_file_count": len(file_inventory),
        "canonical_empirical_file_count": int(
            (
                file_inventory["selected_canonical_source"]
                & ~file_inventory["excluded_from_empirical_evidence"]
            ).sum()
        ),
        "excluded_algorithm_file_count": int(
            file_inventory["excluded_from_empirical_evidence"].sum()
        ),
        "duplicate_content_groups": int(len(duplicate_groups)),
        "yard_unique_containers_across_snapshots": int(
            yard_all["container_id"].nunique()
        ),
        "yard_export_unique_containers_across_snapshots": int(
            yard_export_all["container_id"].nunique()
        ),
        "document_unique_containers_across_snapshots": int(
            docs_all["container_id"].nunique()
        ),
        "containers_seen_in_both_states_across_snapshots": len(transition_rows),
        "containers_document_before_later_yard": int(
            sum(row["document_before_yard"] for row in transition_rows)
        ),
        "voyage_snapshot_rows": len(voyage_frame),
        "voyage_rows_with_all_three_sources": int(
            (
                voyage_frame["has_yard"]
                & voyage_frame["has_documents"]
                & voyage_frame["has_prediction"]
            ).sum()
        ),
        "voyage_rows_documents_and_prediction": int(
            (voyage_frame["has_documents"] & voyage_frame["has_prediction"]).sum()
        ),
        "voyage_rows_yard_and_documents": int(
            (voyage_frame["has_yard"] & voyage_frame["has_documents"]).sum()
        ),
        "prediction_rows_with_observed_lower_bound": len(comparable),
        "prediction_rows_below_observed_lower_bound": int(
            (
                comparable["predicted_total_model_20_40"]
                < comparable["observed_union_lower_bound"]
            ).sum()
        ),
        "model_compatible_unique_observed_export_containers": len(model_pooled),
        "model_compatible_observed_pod_count": int(model_pooled["pod"].nunique()),
        "height_mapping": {"HQ": "HIGH", "PQ": "STD", "MQ": "STD"},
        "caveats": [
            "Yard observations, not-yet-in-yard document records, and predictions are not interchangeable.",
            "Prediction totals are estimates for the complete voyage and are not observed ground truth.",
            "Document plus yard union is only an observed lower bound because undeclared containers may exist.",
            "Repeated snapshots and duplicated files must not be pooled without container-level deduplication.",
            "45-foot prediction volume is reported but excluded from model-compatible 20/40-foot totals.",
            "Import-discharge files are audited separately and are not used to calibrate export stacking demand.",
        ],
    }
    (output_root / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data_analysis"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("local_results/yangshan_data_audit"),
    )
    args = parser.parse_args()
    summary = audit(args.data_root, args.output_root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

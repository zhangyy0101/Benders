"""Build a PNC-primary observed export-call panel with PORT-MIS validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pandas as pd


PROTOCOL_VERSION = "pnc-primary-export-call-volume-v3"
PNC_ANNUAL_CAPACITY_TEU = 5_000_000
PNC_CAPACITY_SOURCE = "https://www.pncport.com/eng/Info/details.do?id=MD032"
PNC_SCHEDULE_SOURCE = "https://svc.pncport.com/info/CMS/Ship/Info.pnc?mCode=MN014"
MAX_MATCH_SCORE_HOURS = 96.0
SCALE_SCENARIOS = {"low": 0.80, "observed": 1.00, "high": 1.20}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_vessel_name(value: object) -> str:
    text = str(value).upper().replace("Ⅱ", "II")
    return re.sub(r"[^A-Z0-9]", "", text)


def stable_call_id(row: pd.Series) -> str:
    identity = "|".join(
        [
            str(row["vessel_code"]),
            str(row["carrier_voyage"]),
            row["berth_time"].isoformat(),
            str(row["berth"]),
        ]
    )
    return "PNC_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16].upper()


def average_teu_per_box(distribution: pd.DataFrame) -> float:
    if abs(distribution["probability"].sum() - 1.0) > 1e-9:
        raise ValueError("Yangshan probabilities do not sum to one")
    return float(
        (
            distribution["probability"]
            * distribution["size_ft"].map({20: 1, 40: 2})
        ).sum()
    )


def one_to_one_matches(
    portmis: pd.DataFrame, pnc: pd.DataFrame
) -> pd.DataFrame:
    candidates = []
    for portmis_index, call in portmis.iterrows():
        same_name = pnc.loc[
            pnc["normalized_vessel_name"] == call["normalized_vessel_name"]
        ]
        for pnc_index, operator_row in same_name.iterrows():
            entry_lag_hours = (
                operator_row["berth_time"] - call["entry_time"]
            ).total_seconds() / 3600
            departure_error_hours = abs(
                (
                    operator_row["departure_time"] - call["departure_time"]
                ).total_seconds()
                / 3600
            )
            score = abs(entry_lag_hours) + departure_error_hours
            candidates.append(
                (
                    score,
                    portmis_index,
                    pnc_index,
                    entry_lag_hours,
                    departure_error_hours,
                )
            )

    used_portmis: set[int] = set()
    used_pnc: set[int] = set()
    matches = []
    for score, portmis_index, pnc_index, entry_lag, departure_error in sorted(
        candidates
    ):
        if (
            score > MAX_MATCH_SCORE_HOURS
            or portmis_index in used_portmis
            or pnc_index in used_pnc
        ):
            continue
        used_portmis.add(portmis_index)
        used_pnc.add(pnc_index)
        matches.append(
            {
                "portmis_index": portmis_index,
                "pnc_index": pnc_index,
                "match_score_hours": score,
                "port_entry_to_berth_hours": entry_lag,
                "departure_error_hours": departure_error,
            }
        )
    return pd.DataFrame(matches)


def build(
    panel_root: Path,
    operator_root: Path,
    yangshan_root: Path,
    output_root: Path,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    portmis_path = panel_root / "pnc_calls_all.csv"
    schedule_path = operator_root / "pnc_operator_schedule.csv"
    distribution_path = yangshan_root / "observed_joint_distribution.csv"
    portmis = pd.read_csv(portmis_path)
    schedule = pd.read_csv(schedule_path)
    distribution = pd.read_csv(distribution_path)

    portmis["entry_time"] = pd.to_datetime(portmis["entry_time"])
    portmis["departure_time"] = pd.to_datetime(portmis["departure_time"])
    schedule["berth_time"] = pd.to_datetime(schedule["berth_time"])
    schedule["departure_time"] = pd.to_datetime(schedule["departure_time"])
    schedule["updated_time"] = pd.to_datetime(schedule["updated_time"])

    # The PNC query includes a few boundary rows from the preceding month.
    # The primary panel is defined solely by PNC berth month.
    schedule = schedule.loc[
        schedule["berth_time"].dt.strftime("%Y_%m") == schedule["period"]
    ].copy()
    schedule = schedule.reset_index(drop=True)
    schedule["normalized_vessel_name"] = schedule["vessel_name"].map(
        normalized_vessel_name
    )
    portmis["normalized_vessel_name"] = portmis["vessel_name"].map(
        normalized_vessel_name
    )
    schedule["call_id"] = schedule.apply(stable_call_id, axis=1)
    if schedule["call_id"].duplicated().any():
        raise ValueError("PNC primary call IDs are not unique")

    matches = one_to_one_matches(portmis, schedule)
    if len(matches) != len(portmis):
        raise ValueError(
            f"Only {len(matches)} of {len(portmis)} PORT-MIS calls matched PNC"
        )
    if matches["portmis_index"].duplicated().any() or matches[
        "pnc_index"
    ].duplicated().any():
        raise ValueError("PNC--PORT-MIS validation matching is not one-to-one")

    portmis_columns = portmis[
        [
            "call_id",
            "vessel_id",
            "entry_time",
            "departure_time",
            "stay_hours",
            "gross_tonnage",
            "berth",
        ]
    ].rename(
        columns={
            "call_id": "portmis_call_id",
            "vessel_id": "portmis_vessel_id",
            "entry_time": "portmis_entry_time",
            "departure_time": "portmis_departure_time",
            "stay_hours": "portmis_stay_hours",
            "gross_tonnage": "portmis_gross_tonnage",
            "berth": "portmis_berth",
        }
    )
    match_enrichment = matches.merge(
        portmis_columns,
        left_on="portmis_index",
        right_index=True,
        how="left",
        validate="one_to_one",
    ).set_index("pnc_index")

    output = schedule[
        [
            "call_id",
            "period",
            "vessel_name",
            "vessel_code",
            "carrier_voyage",
            "operator",
            "route",
            "berth_direction",
            "berth_time",
            "departure_time",
            "berth",
            "gate_cutoff",
            "load_quantity",
            "discharge_quantity",
            "shift_quantity",
            "updated_time",
        ]
    ].copy()
    output["panel_role"] = output["period"].map(
        lambda value: "primary" if value == "2026_05" else "temporal_robustness"
    )
    output["stay_hours"] = (
        output["departure_time"] - output["berth_time"]
    ).dt.total_seconds() / 3600
    output = output.rename(
        columns={
            "load_quantity": "observed_export_boxes",
            "discharge_quantity": "audit_only_import_boxes",
            "updated_time": "pnc_updated_time",
        }
    )
    output["export_demand_eligible"] = output["observed_export_boxes"] > 0
    for scenario, multiplier in SCALE_SCENARIOS.items():
        output[f"export_boxes_{scenario}"] = (
            output["observed_export_boxes"] * multiplier
        ).round().astype(int)

    enrichment_columns = [
        "portmis_call_id",
        "portmis_vessel_id",
        "portmis_entry_time",
        "portmis_departure_time",
        "portmis_stay_hours",
        "portmis_gross_tonnage",
        "portmis_berth",
        "match_score_hours",
        "port_entry_to_berth_hours",
        "departure_error_hours",
    ]
    for column in enrichment_columns:
        output[column] = match_enrichment[column]
    output["portmis_validated"] = output["portmis_call_id"].notna()

    output = output.sort_values(["berth_time", "call_id"]).reset_index(drop=True)
    export_calls = output.loc[output["export_demand_eligible"]].copy()
    output.to_csv(
        output_root / "pnc_calls_all.csv", index=False, encoding="utf-8-sig"
    )
    export_calls.to_csv(
        output_root / "pnc_export_calls.csv", index=False, encoding="utf-8-sig"
    )
    matches.to_csv(
        output_root / "portmis_validation_matches.csv",
        index=False,
        encoding="utf-8-sig",
    )

    average_teu = average_teu_per_box(distribution)
    monthly = (
        output.groupby("period")
        .agg(
            pnc_calls=("call_id", "size"),
            export_calls=("export_demand_eligible", "sum"),
            zero_export_calls=("observed_export_boxes", lambda x: (x == 0).sum()),
            observed_export_boxes=("observed_export_boxes", "sum"),
            audit_only_import_boxes=("audit_only_import_boxes", "sum"),
            median_export_boxes=(
                "observed_export_boxes",
                lambda x: x.loc[x > 0].median(),
            ),
            p90_export_boxes=(
                "observed_export_boxes",
                lambda x: x.loc[x > 0].quantile(0.9),
            ),
            maximum_export_boxes=("observed_export_boxes", "max"),
            portmis_validated_calls=("portmis_validated", "sum"),
        )
        .reset_index()
    )
    monthly["audit_only_total_work_boxes"] = (
        monthly["observed_export_boxes"] + monthly["audit_only_import_boxes"]
    )
    monthly["audit_only_estimated_total_work_teu"] = (
        monthly["audit_only_total_work_boxes"] * average_teu
    )
    monthly.to_csv(
        output_root / "monthly_pnc_export_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    matched_output = output.loc[output["portmis_validated"]]
    annualized_teu = float(
        monthly["audit_only_estimated_total_work_teu"].mean() * 12
    )
    capacity_ratio = annualized_teu / PNC_ANNUAL_CAPACITY_TEU
    audit = {
        "status": "PASS",
        "protocol_version": PROTOCOL_VERSION,
        "primary_source": {
            "name": "PNC operator berth schedule",
            "calls": len(output),
            "period_rule": "PNC berth timestamp falls inside the named month",
            "call_identity": "PNC vessel code, carrier voyage, berth time, berth",
        },
        "export_model_boundary": {
            "model_scope": "export containers only",
            "baseline_field": "observed_export_boxes",
            "definition": "PNC operator-published loading quantity",
            "eligible_calls": len(export_calls),
            "zero_export_calls_excluded_from_demand": int(
                (~output["export_demand_eligible"]).sum()
            ),
            "missing_export_quantity": int(
                output["observed_export_boxes"].isna().sum()
            ),
            "negative_export_quantity": int(
                (output["observed_export_boxes"] < 0).sum()
            ),
            "imputed_calls": 0,
            "import_discharge_role": "audit only; never enters model demand",
        },
        "portmis_independent_validation": {
            "portmis_calls": len(portmis),
            "matched_portmis_calls": len(matches),
            "pnc_calls_validated": int(output["portmis_validated"].sum()),
            "coverage_of_portmis": len(matches) / len(portmis),
            "coverage_of_pnc": float(output["portmis_validated"].mean()),
            "coverage_of_positive_export_pnc": float(
                export_calls["portmis_validated"].mean()
            ),
            "one_to_one": True,
            "median_match_score_hours": float(
                matched_output["match_score_hours"].median()
            ),
            "maximum_match_score_hours": float(
                matched_output["match_score_hours"].max()
            ),
            "p95_departure_error_hours": float(
                matched_output["departure_error_hours"].quantile(0.95)
            ),
        },
        "scale_sensitivity": SCALE_SCENARIOS,
        "capacity_consistency_check": {
            "audit_only": True,
            "official_nominal_annual_capacity_teu": PNC_ANNUAL_CAPACITY_TEU,
            "source": PNC_CAPACITY_SOURCE,
            "yangshan_observed_average_teu_per_box": average_teu,
            "four_month_mean_annualized_total_work_teu": annualized_teu,
            "ratio_to_nominal_capacity": capacity_ratio,
            "gross_inconsistency": not (0.75 <= capacity_ratio <= 1.25),
        },
        "yangshan_role": (
            "joint POD/size/height distribution and virtual-yard calibration"
        ),
        "excluded_from_export_demand": [
            "PNC discharge quantity",
            "PORT-MIS loaded cargo tonnage",
            "Yangshan voyage predictions",
            "PNC annual capacity allocation",
        ],
    }
    if (
        audit["export_model_boundary"]["missing_export_quantity"]
        or audit["export_model_boundary"]["negative_export_quantity"]
        or audit["capacity_consistency_check"]["gross_inconsistency"]
    ):
        audit["status"] = "REVIEW"
    (output_root / "volume_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    source_manifest = pd.DataFrame(
        [
            {
                "role": "primary PNC calls and export quantities",
                "path": schedule_path.as_posix(),
                "bytes": schedule_path.stat().st_size,
                "sha256": sha256(schedule_path),
            },
            {
                "role": "supplementary independent PORT-MIS validation",
                "path": portmis_path.as_posix(),
                "bytes": portmis_path.stat().st_size,
                "sha256": sha256(portmis_path),
            },
            {
                "role": "Yangshan observed joint distribution",
                "path": distribution_path.as_posix(),
                "bytes": distribution_path.stat().st_size,
                "sha256": sha256(distribution_path),
            },
        ]
    )
    source_manifest.to_csv(
        output_root / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )
    output_names = (
        "pnc_calls_all.csv",
        "pnc_export_calls.csv",
        "portmis_validation_matches.csv",
        "monthly_pnc_export_summary.csv",
        "volume_audit.json",
        "source_manifest.csv",
    )
    outputs = {
        name: {
            "bytes": (output_root / name).stat().st_size,
            "sha256": sha256(output_root / name),
        }
        for name in output_names
    }
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "created_by": "scripts/build_pnc_observed_call_volumes.py",
        "primary_source": PNC_SCHEDULE_SOURCE,
        "baseline_export_volume_field": "observed_export_boxes",
        "outputs": outputs,
        "ready_for_attribute_disaggregation": audit["status"] == "PASS",
        "ready_for_formal_experiments": False,
        "next_required_layer": "export POD-size-height integer disaggregation",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--panel-root",
        type=Path,
        default=Path("local_results/protocol_v2_pnc_yangshan/pnc_formal_panel"),
    )
    parser.add_argument(
        "--operator-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/pnc_operator_work_moves"
        ),
    )
    parser.add_argument(
        "--yangshan-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/yangshan_observed_calibration"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/pnc_observed_call_volumes"
        ),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.panel_root,
                args.operator_root,
                args.yangshan_root,
                args.output_root,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

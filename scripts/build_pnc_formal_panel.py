"""Build a verified PNC vessel-call panel from monthly PORT-MIS snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


PERIODS = ("2026_03", "2026_04", "2026_05", "2026_06")
PRIMARY_PERIOD = "2026_05"
PNC_FACILITY_CODE = "MSN"
PNC_SUBCODES = ("04", "05", "06", "07", "08")
OFFICIAL_DATA_PAGE = "https://www.data.go.kr/data/15006353/openapi.do"
OFFICIAL_MAPPING_PAGE = (
    "https://www.busanpa.com/index.bpa?menuCd=DOM_000000103001002005"
)
OFFICIAL_OPERATOR_PAGE = "https://www.pncport.com/eng/Info/details.do?id=MD025"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_period(candidate_root: Path, period: str) -> tuple[pd.DataFrame, dict]:
    source_dir = candidate_root / period
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    audit = json.loads((source_dir / "audit.json").read_text(encoding="utf-8"))
    calls = pd.read_csv(source_dir / "primary_cluster_calls.csv", dtype=str)
    if not manifest["publication_ready"]:
        raise ValueError(f"{period} is not publication-ready")
    if audit["pilot_status"] != "PASS" or not all(audit["gates"].values()):
        raise ValueError(f"{period} failed source gates")
    strict = calls["facility_code"].eq(PNC_FACILITY_CODE) & calls[
        "facility_subcode"
    ].isin(PNC_SUBCODES)
    if not strict.all():
        raise ValueError(f"{period} includes non-PNC facilities")
    calls["period"] = period
    calls["panel_role"] = (
        "primary" if period == PRIMARY_PERIOD else "temporal_robustness"
    )
    calls["entry_time"] = pd.to_datetime(calls["entry_time"])
    calls["departure_time"] = pd.to_datetime(calls["departure_time"])
    calls["stay_hours"] = (
        calls["departure_time"] - calls["entry_time"]
    ).dt.total_seconds() / 3600
    calls["gross_tonnage"] = pd.to_numeric(calls["gross_tonnage"], errors="coerce")
    calls["berth"] = calls["facility_subcode"].map(
        {"04": "B1", "05": "B2", "06": "B3", "07": "B4", "08": "B5"}
    )
    return calls, {"manifest": manifest, "audit": audit, "source_dir": source_dir}


def build(candidate_root: Path, output_root: Path) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    frames = []
    source_info = {}
    for period in PERIODS:
        frame, info = load_period(candidate_root, period)
        frames.append(frame)
        source_info[period] = info
    calls = pd.concat(frames, ignore_index=True)
    calls = calls.sort_values(["entry_time", "call_id"]).reset_index(drop=True)

    if calls["call_id"].duplicated().any():
        raise ValueError("Duplicate call IDs across monthly snapshots")
    if (calls["departure_time"] <= calls["entry_time"]).any():
        raise ValueError("Invalid PNC call time ordering")
    if calls[["call_id", "vessel_id", "entry_time", "departure_time", "berth"]].isna().any().any():
        raise ValueError("Required PNC panel fields are missing")

    output_columns = [
        "call_id",
        "period",
        "panel_role",
        "vessel_id",
        "callsign",
        "vessel_name",
        "entry_time",
        "departure_time",
        "stay_hours",
        "gross_tonnage",
        "berth",
        "facility_code",
        "facility_subcode",
        "facility_name",
        "previous_port_country",
        "previous_port_code",
        "previous_port_name",
        "next_port_country",
        "next_port_code",
        "next_port_name",
    ]
    calls[output_columns].to_csv(
        output_root / "pnc_calls_all.csv", index=False, encoding="utf-8-sig"
    )
    calls.loc[calls["period"] == PRIMARY_PERIOD, output_columns].to_csv(
        output_root / "pnc_calls_primary_2026_05.csv",
        index=False,
        encoding="utf-8-sig",
    )

    monthly = (
        calls.groupby(["period", "panel_role"])
        .agg(
            calls=("call_id", "size"),
            unique_vessels=("vessel_id", "nunique"),
            active_arrival_days=("entry_time", lambda values: values.dt.date.nunique()),
            berths=("berth", "nunique"),
            median_stay_hours=("stay_hours", "median"),
            p90_stay_hours=("stay_hours", lambda values: values.quantile(0.9)),
            median_gross_tonnage=("gross_tonnage", "median"),
        )
        .reset_index()
    )
    monthly.to_csv(
        output_root / "monthly_summary.csv", index=False, encoding="utf-8-sig"
    )

    daily = (
        calls.assign(date=calls["entry_time"].dt.floor("D"))
        .groupby(["date", "period", "panel_role"])
        .agg(
            arrivals=("call_id", "size"),
            unique_vessels=("vessel_id", "nunique"),
            median_stay_hours=("stay_hours", "median"),
            median_gross_tonnage=("gross_tonnage", "median"),
        )
        .reset_index()
    )
    calendar = pd.DataFrame(
        {
            "date": pd.date_range(
                calls["entry_time"].min().floor("D"),
                calls["entry_time"].max().floor("D"),
                freq="D",
            )
        }
    )
    calendar["period"] = calendar["date"].dt.strftime("%Y_%m")
    calendar["panel_role"] = calendar["period"].map(
        lambda value: "primary" if value == PRIMARY_PERIOD else "temporal_robustness"
    )
    daily = calendar.merge(daily, how="left", on=["date", "period", "panel_role"])
    daily["arrivals"] = daily["arrivals"].fillna(0).astype(int)
    daily["unique_vessels"] = daily["unique_vessels"].fillna(0).astype(int)
    daily.to_csv(output_root / "daily_arrivals.csv", index=False, encoding="utf-8-sig")

    berth = (
        calls.groupby(["period", "berth"]).size().rename("calls").reset_index()
    )
    berth["share_within_period"] = berth["calls"] / berth.groupby("period")[
        "calls"
    ].transform("sum")
    berth.to_csv(output_root / "berth_distribution.csv", index=False, encoding="utf-8-sig")

    source_rows = []
    for period, info in source_info.items():
        source_dir = info["source_dir"]
        for filename in ("raw_inbound.json", "raw_outbound.json", "manifest.json", "audit.json"):
            path = source_dir / filename
            source_rows.append(
                {
                    "period": period,
                    "path": path.as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    pd.DataFrame(source_rows).to_csv(
        output_root / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )

    primary = calls.loc[calls["period"] == PRIMARY_PERIOD]
    audit = {
        "status": "PASS",
        "periods": list(PERIODS),
        "primary_period": PRIMARY_PERIOD,
        "total_calls": len(calls),
        "primary_calls": len(primary),
        "total_unique_vessels": int(calls["vessel_id"].nunique()),
        "primary_unique_vessels": int(primary["vessel_id"].nunique()),
        "strict_pnc_facility_mapping": {
            "facility_code": PNC_FACILITY_CODE,
            "facility_subcodes": list(PNC_SUBCODES),
            "all_rows_match": True,
        },
        "quality": {
            "duplicate_call_ids": int(calls["call_id"].duplicated().sum()),
            "invalid_time_rows": int((calls["stay_hours"] <= 0).sum()),
            "missing_required_rows": int(
                calls[
                    ["call_id", "vessel_id", "entry_time", "departure_time", "berth"]
                ]
                .isna()
                .any(axis=1)
                .sum()
            ),
            "covered_berths": sorted(calls["berth"].unique()),
        },
        "data_boundary": {
            "observed": [
                "vessel identity",
                "arrival and departure time",
                "PNC berth",
                "gross tonnage",
                "previous and next vessel port",
            ],
            "not_interpreted_as_box_count": [
                "inbound loaded cargo tonnage",
                "outbound loaded cargo tonnage",
            ],
            "box_volume_anchor_status": "not_yet_built",
            "ready_for_formal_instances": False,
        },
    }
    (output_root / "panel_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    output_files = {}
    for filename in (
        "pnc_calls_all.csv",
        "pnc_calls_primary_2026_05.csv",
        "monthly_summary.csv",
        "daily_arrivals.csv",
        "berth_distribution.csv",
        "source_manifest.csv",
        "panel_audit.json",
    ):
        path = output_root / filename
        output_files[filename] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    manifest = {
        "protocol_version": "pnc-vessel-panel-v2",
        "created_by": "scripts/build_pnc_formal_panel.py",
        "official_data_page": OFFICIAL_DATA_PAGE,
        "official_terminal_mapping_page": OFFICIAL_MAPPING_PAGE,
        "official_operator_page": OFFICIAL_OPERATOR_PAGE,
        "primary_panel": "2026-05",
        "temporal_robustness_panels": ["2026-03", "2026-04", "2026-06"],
        "selection_reason": (
            "May aligns with the Yangshan observation month and passes every "
            "source, time, density, and five-berth coverage gate."
        ),
        "outputs": output_files,
        "formal_readiness": audit["data_boundary"],
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-root",
        type=Path,
        default=Path("local_results/protocol_v2_pnc_yangshan/pnc_candidates"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("local_results/protocol_v2_pnc_yangshan/pnc_formal_panel"),
    )
    args = parser.parse_args()
    print(json.dumps(build(args.candidate_root, args.output_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Build demand-linked, model-compatible virtual-yard templates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rolling_data import _integer_profile, build_initial_locked_inventory


PROTOCOL_VERSION = "yangshan-calibrated-virtual-yard-v1"
SEED = 20260728
RECEIVING_HOURS = 72
MAX_INITIAL_BAY_FILL = 0.85
NOMINAL_OLD_OUTBOUND_PER_6H = 120
PROFILES = {
    "observed_full": {
        "initial_utilization": "calibration_mean",
        "target_peak_ratio": None,
    },
    "capacity_relief_080": {
        "initial_utilization": 0.535,
        "target_peak_ratio": 0.80,
    },
    "high_pressure": {
        "initial_utilization": "heldout",
        "target_peak_ratio": 0.90,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def peak_active_by_size(
    calls: pd.DataFrame, groups: pd.DataFrame
) -> pd.DataFrame:
    group_totals = groups.groupby(["call_id", "size_ft"])["boxes"].sum()
    rows = []
    for period, period_calls in calls.groupby("period"):
        events = sorted(
            set(period_calls["entry_time"] - pd.Timedelta(hours=RECEIVING_HOURS))
            | set(period_calls["departure_time"])
        )
        for size in (20, 40):
            best_quantity = -1
            best_time = None
            for event in events:
                active_ids = period_calls.loc[
                    (
                        period_calls["entry_time"]
                        - pd.Timedelta(hours=RECEIVING_HOURS)
                        <= event
                    )
                    & (period_calls["departure_time"] > event),
                    "call_id",
                ]
                quantity = sum(
                    int(group_totals.get((call_id, size), 0))
                    for call_id in active_ids
                )
                if quantity > best_quantity:
                    best_quantity = quantity
                    best_time = event
            rows.append(
                {
                    "period": period,
                    "size_ft": size,
                    "peak_conservative_active_boxes": best_quantity,
                    "peak_time": best_time,
                }
            )
    return pd.DataFrame(rows)


def dynamic_inventory_diagnostics(
    calls: pd.DataFrame,
    groups: pd.DataFrame,
    bays: pd.DataFrame,
    locked: pd.DataFrame,
    profile: str,
) -> list[dict]:
    capacity_by_size = bays.groupby("size_ft")["capacity_boxes"].sum().to_dict()
    bay_sizes = bays.set_index("bay")["size_ft"]
    locked_with_size = locked.assign(size_ft=locked["bay"].map(bay_sizes))
    group_totals = groups.groupby(["call_id", "size_ft"])["boxes"].sum()
    triangle = [1, 2, 3, 4, 5, 6, 6, 5, 4, 3, 2, 1]
    rows = []
    for period, period_calls in calls.groupby("period"):
        epoch = (
            period_calls["entry_time"].min()
            - pd.Timedelta(hours=RECEIVING_HOURS)
        ).floor("6h")
        arrivals: dict[tuple[str, int, int], int] = {}
        releases: dict[str, int] = {}
        for _, call in period_calls.iterrows():
            call_id = call["call_id"]
            start = max(
                0,
                math.floor(
                    (
                        call["entry_time"]
                        - pd.Timedelta(hours=RECEIVING_HOURS)
                        - epoch
                    ).total_seconds()
                    / 21600
                ),
            )
            releases[call_id] = max(
                start + 1,
                math.ceil(
                    (call["departure_time"] - epoch).total_seconds() / 21600
                ),
            )
            for size in (20, 40):
                total = int(group_totals.get((call_id, size), 0))
                for offset, quantity in enumerate(
                    _integer_profile(total, triangle)
                ):
                    if quantity:
                        arrivals[call_id, size, start + offset] = quantity

        last_period = max(releases.values())
        for size in (20, 40):
            best = (-1.0, 0, 0, 0)
            ratios = []
            for time_index in range(last_period + 1):
                old_boxes = int(
                    locked_with_size.loc[
                        (locked_with_size["size_ft"] == size)
                        & (
                            locked_with_size["release_period_6h"]
                            > time_index
                        ),
                        "locked_boxes",
                    ].sum()
                )
                new_boxes = sum(
                    quantity
                    for (call_id, candidate_size, arrival), quantity
                    in arrivals.items()
                    if candidate_size == size
                    and arrival <= time_index < releases[call_id]
                )
                ratio = (old_boxes + new_boxes) / capacity_by_size[size]
                ratios.append(ratio)
                if ratio > best[0]:
                    best = (ratio, time_index, old_boxes, new_boxes)
            ratio, peak_period, peak_locked, peak_new = best
            rows.append(
                {
                    "yard_profile": profile,
                    "period": period,
                    "size_ft": size,
                    "peak_period_6h": peak_period,
                    "peak_time": epoch
                    + pd.Timedelta(hours=6 * peak_period),
                    "locked_boxes_at_peak": peak_locked,
                    "new_export_boxes_at_peak": peak_new,
                    "capacity_boxes": int(capacity_by_size[size]),
                    "dynamic_peak_load_ratio": ratio,
                    "dynamic_mean_load_ratio": sum(ratios) / len(ratios),
                    "dynamic_p90_load_ratio": float(
                        pd.Series(ratios).quantile(0.9)
                    ),
                }
            )
    return rows


def resolve_utilization(
    value: float | str, yard: pd.DataFrame
) -> float:
    if value == "calibration_mean":
        return float(
            yard.loc[yard["snapshot"].isin([508, 519]), "occupied_slot_share"].mean()
        )
    if value == "heldout":
        return float(
            yard.loc[yard["snapshot"] == 525, "occupied_slot_share"].iloc[0]
        )
    return float(value)


def allocate_bay_counts(
    profile: str,
    utilization: float,
    target_peak_ratio: float | None,
    peak_by_size: dict[int, int],
    full_bays: int,
    size_share_20: float,
    mean_capacity: float,
) -> dict[int, int]:
    if profile == "observed_full":
        twenty = round(full_bays * size_share_20)
        return {20: twenty, 40: full_bays - twenty}
    if target_peak_ratio is None or target_peak_ratio <= utilization:
        raise ValueError("pressure target must exceed initial utilization")
    result = {}
    for size in (20, 40):
        required_capacity = math.ceil(
            peak_by_size[size] / (target_peak_ratio - utilization)
        )
        result[size] = math.ceil(required_capacity / mean_capacity)
    return result


def build_profile(
    name: str,
    utilization: float,
    target_peak_ratio: float | None,
    bay_counts: dict[int, int],
    mean_capacity: float,
    bays_per_area_anchor: float,
    tiers_anchor: int,
    high_share: float,
    output_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    total_bays = sum(bay_counts.values())
    num_areas = max(1, round(total_bays / bays_per_area_anchor))
    bay_specs = []
    size_sequence = [20] * bay_counts[20] + [40] * bay_counts[40]
    rng = random.Random(SEED + sum(map(ord, name)))
    rng.shuffle(size_sequence)
    base_capacity = math.floor(mean_capacity)
    extra_count = round(total_bays * (mean_capacity - base_capacity))
    extra_indices = set(rng.sample(range(total_bays), extra_count))
    for index, size in enumerate(size_sequence):
        area_index = index % num_areas
        position = index // num_areas
        bay_id = f"A{area_index + 1:03d}_Y{position + 1:03d}"
        bay_specs.append(
            {
                "yard_profile": name,
                "area": f"A{area_index + 1:03d}",
                "bay": bay_id,
                "size_ft": size,
                "capacity_boxes": base_capacity
                + (1 if index in extra_indices else 0),
                "tiers_anchor": tiers_anchor,
            }
        )
    bays = pd.DataFrame(bay_specs)
    capacity = dict(zip(bays["bay"], bays["capacity_boxes"]))
    bay_size = dict(zip(bays["bay"], bays["size_ft"]))
    locked, locked_height, diagnostics = build_initial_locked_inventory(
        bays=bays["bay"],
        capacity=capacity,
        bay_size=bay_size,
        heights=("STD", "HIGH"),
        target_utilization=utilization,
        seed=SEED + sum(map(ord, name)),
        max_fill_ratio=MAX_INITIAL_BAY_FILL,
    )

    locked_rows = []
    old_totals: dict[str, int] = {}
    for bay, old_ship in sorted(locked):
        quantity = int(locked[bay, old_ship])
        old_totals[old_ship] = old_totals.get(old_ship, 0) + quantity
        height = "HIGH" if rng.random() < high_share else "STD"
        locked_rows.append(
            {
                "yard_profile": name,
                "bay": bay,
                "old_ship": old_ship,
                "locked_boxes": quantity,
                "height_class": height,
            }
        )
    old_release = {
        old_ship: max(
            1, math.ceil(quantity / NOMINAL_OLD_OUTBOUND_PER_6H)
        )
        for old_ship, quantity in old_totals.items()
    }
    locked_frame = pd.DataFrame(locked_rows)
    locked_frame["release_period_6h"] = locked_frame["old_ship"].map(old_release)

    capacity_by_size = bays.groupby("size_ft")["capacity_boxes"].sum().to_dict()
    locked_by_size = (
        locked_frame.merge(bays[["bay", "size_ft"]], on="bay")
        .groupby("size_ft")["locked_boxes"]
        .sum()
        .to_dict()
    )
    summary = {
        "profile": name,
        "areas": num_areas,
        "bays": total_bays,
        "tiers_anchor": tiers_anchor,
        "total_capacity_boxes": int(bays["capacity_boxes"].sum()),
        "capacity_by_size": {
            str(size): int(capacity_by_size[size]) for size in (20, 40)
        },
        "requested_initial_utilization": utilization,
        "realized_initial_utilization": diagnostics[
            "realized_initial_utilization"
        ],
        "initial_locked_boxes": int(locked_frame["locked_boxes"].sum()),
        "locked_by_size": {
            str(size): int(locked_by_size.get(size, 0)) for size in (20, 40)
        },
        "maximum_initial_bay_fill_ratio": MAX_INITIAL_BAY_FILL,
        "target_peak_ratio": target_peak_ratio,
        "height_high_probability_anchor": high_share,
        "old_inventory_release_basis": (
            f"semi-synthetic {NOMINAL_OLD_OUTBOUND_PER_6H} boxes per 6h"
        ),
    }
    profile_root = output_root / name
    profile_root.mkdir(parents=True, exist_ok=True)
    bays.to_csv(
        profile_root / "yard_bays.csv", index=False, encoding="utf-8-sig"
    )
    locked_frame.to_csv(
        profile_root / "initial_locked_inventory.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (profile_root / "yard_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return bays, locked_frame, summary


def build(
    attribute_root: Path,
    yangshan_root: Path,
    output_root: Path,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    calls_path = attribute_root / "export_calls_model_ready.csv"
    groups_path = attribute_root / "export_groups_model_ready.csv"
    yard_path = yangshan_root / "yard_calibration.csv"
    joint_path = yangshan_root / "observed_joint_distribution.csv"
    calls = pd.read_csv(calls_path, parse_dates=["entry_time", "departure_time"])
    groups = pd.read_csv(groups_path)
    yard = pd.read_csv(yard_path)
    joint = pd.read_csv(joint_path)

    peaks = peak_active_by_size(calls, groups)
    peaks.to_csv(
        output_root / "receiving_overlap_upper_bound.csv",
        index=False,
        encoding="utf-8-sig",
    )
    peak_by_size = (
        peaks.groupby("size_ft")["peak_conservative_active_boxes"].max().to_dict()
    )
    full_bays = round(
        yard.loc[yard["snapshot"].isin([508, 519]), "bays"].mean()
    )
    calibration_yard = yard.loc[yard["snapshot"].isin([508, 519])]
    bays_per_area_anchor = float(
        calibration_yard["bays"].sum() / calibration_yard["areas"].sum()
    )
    tiers_anchor = int(calibration_yard["tiers"].max())
    mean_capacity = float(
        yard.loc[yard["snapshot"].isin([508, 519]), "slot_rows"].sum()
        / yard.loc[yard["snapshot"].isin([508, 519]), "bays"].sum()
    )
    size_share_20 = float(
        joint.loc[joint["size_ft"] == 20, "probability"].sum()
    )
    high_share = float(
        joint.loc[joint["height_class"] == "HIGH", "probability"].sum()
    )

    profile_outputs = {}
    diagnostic_rows = []
    for name, spec in PROFILES.items():
        utilization = resolve_utilization(spec["initial_utilization"], yard)
        bay_counts = allocate_bay_counts(
            name,
            utilization,
            spec["target_peak_ratio"],
            peak_by_size,
            full_bays,
            size_share_20,
            mean_capacity,
        )
        bays, locked, summary = build_profile(
            name,
            utilization,
            spec["target_peak_ratio"],
            bay_counts,
            mean_capacity,
            bays_per_area_anchor,
            tiers_anchor,
            high_share,
            output_root,
        )
        diagnostic_rows.extend(
            dynamic_inventory_diagnostics(calls, groups, bays, locked, name)
        )
        profile_root = output_root / name
        profile_outputs[name] = {
            "summary": summary,
            "files": {
                filename: {
                    "bytes": (profile_root / filename).stat().st_size,
                    "sha256": sha256(profile_root / filename),
                }
                for filename in (
                    "yard_bays.csv",
                    "initial_locked_inventory.csv",
                    "yard_summary.json",
                )
            },
        }

    diagnostics = pd.DataFrame(diagnostic_rows)
    diagnostics.to_csv(
        output_root / "yard_pressure_diagnostics.csv",
        index=False,
        encoding="utf-8-sig",
    )
    audit = {
        "status": "PASS",
        "protocol_version": PROTOCOL_VERSION,
        "source_yangshan_snapshots": ["0508", "0519", "0525"],
        "profiles": list(PROFILES),
        "observed_anchor": {
            "yard_scope": "areas whose function list contains OF",
            "of_areas_listed": int(yard["of_areas_listed"].max()),
            "areas_with_slots": [
                int(yard["areas"].min()),
                int(yard["areas"].max()),
            ],
            "bays_range": [
                int(yard["bays"].min()),
                int(yard["bays"].max()),
            ],
            "slot_rows_range": [
                int(yard["slot_rows"].min()),
                int(yard["slot_rows"].max()),
            ],
            "tiers": tiers_anchor,
            "occupied_share_range": [
                float(yard["occupied_slot_share"].min()),
                float(yard["occupied_slot_share"].max()),
            ],
            "mean_capacity_boxes_per_bay": mean_capacity,
        },
        "demand_link": {
            "receiving_window_hours": RECEIVING_HOURS,
            "peak_by_size": {
                str(size): int(peak_by_size[size]) for size in (20, 40)
            },
            "upper_bound_rule": (
                "reported separately: all boxes assigned to a call overlap "
                "throughout the 72-hour receiving window until departure"
            ),
            "dynamic_rule": (
                "new boxes follow a 12-period receiving curve, leave at PNC "
                "departure, and initial owners follow their recorded "
                "semi-synthetic release periods"
            ),
        },
        "maximum_profile_load_ratio": {
            name: float(
                diagnostics.loc[
                    diagnostics["yard_profile"] == name,
                    "dynamic_peak_load_ratio",
                ].max()
            )
            for name in PROFILES
        },
        "mean_profile_load_ratio": {
            name: float(
                diagnostics.loc[
                    diagnostics["yard_profile"] == name,
                    "dynamic_mean_load_ratio",
                ].mean()
            )
            for name in PROFILES
        },
        "model_constraints_preserved": [
            "integer bay capacity",
            "20/40-foot bay compatibility",
            "single locked height per occupied bay-owner",
            "initial inventory occupancy",
            "whole-owner release period",
            f"{tiers_anchor}-tier physical anchor",
        ],
        "not_claimed": [
            "physical PNC yard layout",
            "observed PNC initial inventory",
            "observed old-container release schedule",
        ],
    }
    if (
        diagnostics["dynamic_peak_load_ratio"].max() > 1.0
        or any(
            abs(
                profile_outputs[name]["summary"][
                    "realized_initial_utilization"
                ]
                - profile_outputs[name]["summary"][
                    "requested_initial_utilization"
                ]
            )
            > 1e-4
            for name in PROFILES
        )
    ):
        audit["status"] = "FAIL"
    (output_root / "yard_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    source_manifest = pd.DataFrame(
        [
            {
                "role": "model-ready PNC export calls",
                "path": calls_path.as_posix(),
                "sha256": sha256(calls_path),
            },
            {
                "role": "model-ready PNC export groups",
                "path": groups_path.as_posix(),
                "sha256": sha256(groups_path),
            },
            {
                "role": "Yangshan yard calibration",
                "path": yard_path.as_posix(),
                "sha256": sha256(yard_path),
            },
            {
                "role": "Yangshan joint attribute calibration",
                "path": joint_path.as_posix(),
                "sha256": sha256(joint_path),
            },
        ]
    )
    source_manifest.to_csv(
        output_root / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "created_by": "scripts/build_yangshan_calibrated_virtual_yard.py",
        "seed": SEED,
        "profiles": profile_outputs,
        "audit_sha256": sha256(output_root / "yard_audit.json"),
        "pressure_diagnostics_sha256": sha256(
            output_root / "yard_pressure_diagnostics.csv"
        ),
        "ready_for_instance_assembly": audit["status"] == "PASS",
        "ready_for_formal_experiments": False,
        "next_required_layer": (
            "assemble rolling instances and obtain integer packing certificates"
        ),
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attribute-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/"
            "pnc_export_attribute_disaggregation"
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
            "local_results/protocol_v2_pnc_yangshan/"
            "yangshan_calibrated_virtual_yard"
        ),
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.attribute_root, args.yangshan_root, args.output_root),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

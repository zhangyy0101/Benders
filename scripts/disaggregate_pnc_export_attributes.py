"""Integer-disaggregate observed PNC export totals into Yangshan joint groups."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PROTOCOL_VERSION = "pnc-yangshan-export-attributes-v1"
DEFAULT_SEED = 20260728
SCENARIOS = {
    "low": "export_boxes_low",
    "observed": "export_boxes_observed",
    "high": "export_boxes_high",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def largest_remainder(total: int, probabilities: np.ndarray) -> np.ndarray:
    raw = probabilities * total
    result = np.floor(raw).astype(np.int64)
    remainder = int(total - result.sum())
    if remainder:
        order = np.lexsort((np.arange(len(raw)), -(raw - result)))
        result[order[:remainder]] += 1
    if result.sum() != total or (result < 0).any():
        raise ValueError("largest-remainder allocation failed")
    return result


def tv_distance(left: pd.Series, right: pd.Series) -> float:
    support = left.index.union(right.index)
    return float(
        0.5
        * (
            left.reindex(support, fill_value=0)
            - right.reindex(support, fill_value=0)
        )
        .abs()
        .sum()
    )


def disaggregate_period(
    calls: pd.DataFrame,
    distribution: pd.DataFrame,
    voyage_profiles: pd.DataFrame,
    quantity_column: str,
    scenario: str,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    profile_sizes = (
        voyage_profiles[
            ["IYC_EVOY_ID", "voyage_observed_boxes", "voyage_observed_pods"]
        ]
        .drop_duplicates("IYC_EVOY_ID")
        .reset_index(drop=True)
    )
    group_index = {
        (row.pod, int(row.size_ft), row.height_class): index
        for index, row in distribution.iterrows()
    }
    aggregate_target = largest_remainder(
        int(calls[quantity_column].sum()),
        distribution["probability"].to_numpy(dtype=float),
    )
    aggregate_allocated = np.zeros(len(distribution), dtype=np.int64)

    group_rows = []
    call_rows = []
    processing_order = sorted(
        range(len(calls)),
        key=lambda position: (
            -int(calls.iloc[position][quantity_column]),
            float(rng.random()),
        ),
    )
    selected: dict[int, tuple[pd.Series, pd.DataFrame, np.ndarray]] = {}
    for call_position in processing_order:
        call = calls.iloc[call_position]
        quantity = int(call[quantity_column])
        distances = np.abs(
            np.log1p(profile_sizes["voyage_observed_boxes"].to_numpy())
            - np.log1p(quantity)
        )
        nearest = np.argsort(distances, kind="stable")[: min(30, len(distances))]
        candidates = []
        for chosen_position in nearest:
            chosen = profile_sizes.iloc[int(chosen_position)]
            profile = voyage_profiles.loc[
                voyage_profiles["IYC_EVOY_ID"] == chosen["IYC_EVOY_ID"]
            ].sort_values(["pod", "size_ft", "height_class"])
            profile_draw = largest_remainder(
                quantity,
                profile["within_voyage_probability"].to_numpy(dtype=float),
            )
            full_draw = np.zeros(len(distribution), dtype=np.int64)
            for profile_position, profile_row in profile.reset_index(
                drop=True
            ).iterrows():
                key = (
                    profile_row["pod"],
                    int(profile_row["size_ft"]),
                    profile_row["height_class"],
                )
                full_draw[group_index[key]] = profile_draw[profile_position]
            imbalance = int(
                np.abs(
                    aggregate_target - aggregate_allocated - full_draw
                ).sum()
            )
            candidates.append(
                (imbalance, float(rng.random()), chosen, profile, profile_draw)
            )
        _, _, chosen, profile, draw = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        for profile_position, profile_row in profile.reset_index(
            drop=True
        ).iterrows():
            key = (
                profile_row["pod"],
                int(profile_row["size_ft"]),
                profile_row["height_class"],
            )
            aggregate_allocated[group_index[key]] += draw[profile_position]
        selected[call_position] = (chosen, profile, draw)

    for call_position in range(len(calls)):
        call = calls.iloc[call_position]
        quantity = int(call[quantity_column])
        chosen, profile, draw = selected[call_position]
        positive = np.flatnonzero(draw)
        forty = 0
        high = 0
        teu = 0
        pods: set[str] = set()
        for group_position in positive:
            group = profile.iloc[group_position]
            boxes = int(draw[group_position])
            size = int(group["size_ft"])
            height = str(group["height_class"])
            group_teu = boxes * (size // 20)
            forty += boxes if size == 40 else 0
            high += boxes if height == "HIGH" else 0
            teu += group_teu
            pods.add(str(group["pod"]))
            group_rows.append(
                {
                    "scenario": scenario,
                    "period": call["period"],
                    "panel_role": call["panel_role"],
                    "call_id": call["call_id"],
                    "pod": group["pod"],
                    "size_ft": size,
                    "height_class": height,
                    "boxes": boxes,
                    "teu": group_teu,
                    "field_origin": (
                        "semi_synthetic_yangshan_joint_distribution"
                    ),
                }
            )
        call_rows.append(
            {
                "scenario": scenario,
                "period": call["period"],
                "panel_role": call["panel_role"],
                "call_id": call["call_id"],
                "vessel_name": call["vessel_name"],
                "vessel_code": call["vessel_code"],
                "carrier_voyage": call["carrier_voyage"],
                "operator": call["operator"],
                "route": call["route"],
                "entry_time": call["berth_time"],
                "departure_time": call["departure_time"],
                "berth": call["berth"],
                "observed_export_boxes": int(call["observed_export_boxes"]),
                "synthetic_export_boxes": quantity,
                "synthetic_export_teu": teu,
                "synthetic_pod_count": len(pods),
                "synthetic_20ft_boxes": quantity - forty,
                "synthetic_40ft_boxes": forty,
                "synthetic_high_boxes": high,
                "yangshan_profile_voyage_id": chosen["IYC_EVOY_ID"],
                "yangshan_profile_observed_boxes": int(
                    chosen["voyage_observed_boxes"]
                ),
                "yangshan_profile_observed_pods": int(
                    chosen["voyage_observed_pods"]
                ),
                "portmis_validated": call["portmis_validated"],
                "demand_origin": (
                    "pnc_observed_export_total_yangshan_joint_attributes"
                ),
            }
        )
    return pd.DataFrame(call_rows), pd.DataFrame(group_rows)


def distribution_from_groups(
    groups: pd.DataFrame, columns: list[str]
) -> pd.Series:
    totals = groups.groupby(columns)["boxes"].sum()
    return totals / totals.sum()


def build(
    volume_root: Path,
    yangshan_root: Path,
    output_root: Path,
    seed: int,
) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    calls_path = volume_root / "pnc_export_calls.csv"
    calibration_path = yangshan_root / "observed_joint_distribution.csv"
    heldout_path = yangshan_root / "heldout_joint_distribution.csv"
    profile_path = yangshan_root / "observed_voyage_group_profiles.csv"
    calls = pd.read_csv(calls_path)
    calibration = pd.read_csv(calibration_path)
    heldout = pd.read_csv(heldout_path)
    voyage_profiles = pd.read_csv(profile_path)

    calibration = calibration.sort_values(
        ["pod", "size_ft", "height_class"]
    ).reset_index(drop=True)
    if set(calibration["size_ft"]) != {20, 40}:
        raise ValueError("calibration contains unsupported sizes")
    if set(calibration["height_class"]) != {"STD", "HIGH"}:
        raise ValueError("calibration contains unsupported heights")
    if abs(calibration["probability"].sum() - 1.0) > 1e-9:
        raise ValueError("calibration probabilities do not sum to one")

    all_call_frames = []
    all_group_frames = []
    for scenario_index, (scenario, quantity_column) in enumerate(
        SCENARIOS.items()
    ):
        for period_index, (period, period_calls) in enumerate(
            calls.groupby("period", sort=True)
        ):
            period_seed = seed + scenario_index * 10_000 + period_index
            rng = np.random.default_rng(period_seed)
            call_frame, group_frame = disaggregate_period(
                period_calls.sort_values(["berth_time", "call_id"]).reset_index(
                    drop=True
                ),
                calibration,
                voyage_profiles,
                quantity_column,
                scenario,
                rng,
            )
            all_call_frames.append(call_frame)
            all_group_frames.append(group_frame)

    scenario_calls = pd.concat(all_call_frames, ignore_index=True)
    scenario_groups = pd.concat(all_group_frames, ignore_index=True)
    observed_calls = scenario_calls.loc[
        scenario_calls["scenario"] == "observed"
    ].drop(columns="scenario")
    observed_groups = scenario_groups.loc[
        scenario_groups["scenario"] == "observed"
    ].drop(columns="scenario")

    scenario_calls.to_csv(
        output_root / "export_calls_scenarios.csv",
        index=False,
        encoding="utf-8-sig",
    )
    scenario_groups.to_csv(
        output_root / "export_groups_scenarios.csv",
        index=False,
        encoding="utf-8-sig",
    )
    observed_calls.to_csv(
        output_root / "export_calls_model_ready.csv",
        index=False,
        encoding="utf-8-sig",
    )
    observed_groups.to_csv(
        output_root / "export_groups_model_ready.csv",
        index=False,
        encoding="utf-8-sig",
    )

    validation_rows = []
    calibration_series = {
        "joint": calibration.set_index(
            ["pod", "size_ft", "height_class"]
        )["probability"],
        "pod": calibration.groupby("pod")["probability"].sum(),
        "size": calibration.groupby("size_ft")["probability"].sum(),
        "height": calibration.groupby("height_class")["probability"].sum(),
    }
    heldout_series = {
        "joint": heldout.set_index(["pod", "size_ft", "height_class"])[
            "probability"
        ],
        "pod": heldout.groupby("pod")["probability"].sum(),
        "size": heldout.groupby("size_ft")["probability"].sum(),
        "height": heldout.groupby("height_class")["probability"].sum(),
    }
    dimensions = {
        "joint": ["pod", "size_ft", "height_class"],
        "pod": ["pod"],
        "size": ["size_ft"],
        "height": ["height_class"],
    }
    for scenario, groups in scenario_groups.groupby("scenario"):
        for period, period_groups in groups.groupby("period"):
            for dimension, columns in dimensions.items():
                generated = distribution_from_groups(period_groups, columns)
                validation_rows.append(
                    {
                        "scenario": scenario,
                        "period": period,
                        "dimension": dimension,
                        "tv_to_calibration": tv_distance(
                            generated, calibration_series[dimension]
                        ),
                        "tv_to_heldout": tv_distance(
                            generated, heldout_series[dimension]
                        ),
                    }
                )
    validation = pd.DataFrame(validation_rows)
    validation.to_csv(
        output_root / "distribution_validation.csv",
        index=False,
        encoding="utf-8-sig",
    )

    reconciled = (
        scenario_groups.groupby(["scenario", "call_id"])["boxes"].sum()
        .rename("group_boxes")
        .reset_index()
        .merge(
            scenario_calls[
                ["scenario", "call_id", "synthetic_export_boxes"]
            ],
            on=["scenario", "call_id"],
            validate="one_to_one",
        )
    )
    audit = {
        "status": "PASS",
        "protocol_version": PROTOCOL_VERSION,
        "random_seed": seed,
        "source_export_calls": len(calls),
        "scenarios": list(SCENARIOS),
        "scenario_call_rows": len(scenario_calls),
        "scenario_group_rows": len(scenario_groups),
        "observed_call_rows": len(observed_calls),
        "observed_group_rows": len(observed_groups),
        "conservation_failures": int(
            (
                reconciled["group_boxes"]
                != reconciled["synthetic_export_boxes"]
            ).sum()
        ),
        "nonpositive_group_rows": int((scenario_groups["boxes"] <= 0).sum()),
        "unsupported_size_rows": int(
            (~scenario_groups["size_ft"].isin([20, 40])).sum()
        ),
        "unsupported_height_rows": int(
            (~scenario_groups["height_class"].isin(["STD", "HIGH"])).sum()
        ),
        "observed_total_boxes": int(observed_calls["synthetic_export_boxes"].sum()),
        "observed_group_boxes": int(observed_groups["boxes"].sum()),
        "observed_total_teu": int(observed_groups["teu"].sum()),
        "maximum_monthly_joint_tv_to_calibration": float(
            validation.loc[
                (validation["scenario"] == "observed")
                & (validation["dimension"] == "joint"),
                "tv_to_calibration",
            ].max()
        ),
        "observed_pod_count_per_call": {
            "minimum": int(observed_calls["synthetic_pod_count"].min()),
            "median": float(observed_calls["synthetic_pod_count"].median()),
            "maximum": int(observed_calls["synthetic_pod_count"].max()),
        },
        "profile_selection": (
            "seeded size-matched and aggregate-balance-guided bootstrap from "
            "observed Yangshan voyage joint profiles; 30 nearest profiles on "
            "log box count"
        ),
        "heldout_role": "validation only; never used to fit allocations",
        "model_boundary": {
            "cargo_direction": "export only",
            "attributes": ["pod", "size_ft", "height_class"],
            "sizes_ft": [20, 40],
            "height_classes": ["STD", "HIGH"],
        },
    }
    if any(
        audit[key]
        for key in (
            "conservation_failures",
            "nonpositive_group_rows",
            "unsupported_size_rows",
            "unsupported_height_rows",
        )
    ):
        audit["status"] = "FAIL"
    (output_root / "attribute_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    source_manifest = pd.DataFrame(
        [
            {
                "role": "PNC observed positive export calls",
                "path": calls_path.as_posix(),
                "sha256": sha256(calls_path),
            },
            {
                "role": "Yangshan calibration joint distribution",
                "path": calibration_path.as_posix(),
                "sha256": sha256(calibration_path),
            },
            {
                "role": "Yangshan held-out validation distribution",
                "path": heldout_path.as_posix(),
                "sha256": sha256(heldout_path),
            },
            {
                "role": "Yangshan observed per-voyage joint profiles",
                "path": profile_path.as_posix(),
                "sha256": sha256(profile_path),
            },
        ]
    )
    source_manifest.to_csv(
        output_root / "source_manifest.csv", index=False, encoding="utf-8-sig"
    )
    output_names = (
        "export_calls_scenarios.csv",
        "export_groups_scenarios.csv",
        "export_calls_model_ready.csv",
        "export_groups_model_ready.csv",
        "distribution_validation.csv",
        "attribute_audit.json",
        "source_manifest.csv",
    )
    manifest = {
        "protocol_version": PROTOCOL_VERSION,
        "created_by": "scripts/disaggregate_pnc_export_attributes.py",
        "random_seed": seed,
        "outputs": {
            name: {
                "bytes": (output_root / name).stat().st_size,
                "sha256": sha256(output_root / name),
            }
            for name in output_names
        },
        "ready_for_yard_generation": audit["status"] == "PASS",
        "ready_for_formal_experiments": False,
        "next_required_layer": "Yangshan-calibrated model-compatible virtual yard",
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--volume-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/pnc_observed_call_volumes"
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
            "pnc_export_attribute_disaggregation"
        ),
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.volume_root,
                args.yangshan_root,
                args.output_root,
                args.seed,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

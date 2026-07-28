"""Assemble and certify one PNC--Yangshan V2 rolling pilot instance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formal_experiments import INSTANCE_PROTOCOL, write_instance_bundle
from rolling_model import solve_full_horizon_packing_oracle
from scripts.run_portmis_end_to_end import build_portmis_rolling_case


DATA_PROTOCOL = "pnc-yangshan-formal-instance-v2"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def select_yard(
    bay_rows: list[dict[str, str]],
    inventory_rows: list[dict[str, str]],
    *,
    incoming_boxes: int,
    minimum_free_factor: float,
    selected_area_count: int | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict]:
    """Select whole OF-calibrated areas until free slots cover pilot demand."""
    locked_by_bay: dict[str, int] = {}
    for row in inventory_rows:
        locked_by_bay[row["bay"]] = (
            locked_by_bay.get(row["bay"], 0) + int(row["locked_boxes"])
        )
    by_area: dict[str, list[dict[str, str]]] = {}
    for row in bay_rows:
        by_area.setdefault(row["area"], []).append(row)
    area_order = sorted(
        by_area,
        key=lambda area: (
            -sum(
                int(row["capacity_boxes"]) - locked_by_bay.get(row["bay"], 0)
                for row in by_area[area]
            ),
            area,
        ),
    )
    required_free = math.ceil(incoming_boxes * minimum_free_factor)
    selected_areas: list[str] = []
    free_slots = 0
    for area in area_order:
        selected_areas.append(area)
        free_slots += sum(
            int(row["capacity_boxes"]) - locked_by_bay.get(row["bay"], 0)
            for row in by_area[area]
        )
        if (
            selected_area_count is not None
            and len(selected_areas) >= selected_area_count
        ) or (
            selected_area_count is None and free_slots >= required_free
        ):
            break
    if selected_area_count is None and free_slots < required_free:
        raise RuntimeError("calibrated yard cannot cover requested pilot demand")
    selected = [
        row for area in selected_areas for row in by_area[area]
    ]
    selected_bays = {row["bay"] for row in selected}
    inventory = [row for row in inventory_rows if row["bay"] in selected_bays]
    capacity = sum(int(row["capacity_boxes"]) for row in selected)
    locked = sum(int(row["locked_boxes"]) for row in inventory)
    return selected, inventory, {
        "selection_rule": (
            "fixed_count_whole_areas_ranked_by_observed_free_slots"
            if selected_area_count is not None
            else "whole_areas_ranked_by_observed_free_slots"
        ),
        "minimum_free_factor": minimum_free_factor,
        "selected_area_count": len(selected_areas),
        "selected_bay_count": len(selected),
        "capacity_boxes": capacity,
        "initial_locked_boxes": locked,
        "initial_utilization": locked / capacity,
        "free_slots": capacity - locked,
        "incoming_booking_boxes": incoming_boxes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    base = Path("local_results/protocol_v2_pnc_yangshan")
    parser.add_argument(
        "--attribute-root",
        type=Path,
        default=base / "pnc_export_attribute_disaggregation",
    )
    parser.add_argument(
        "--yard-root",
        type=Path,
        default=base / "yangshan_calibrated_virtual_yard",
    )
    parser.add_argument("--yard-profile", default="capacity_relief_080")
    parser.add_argument("--period", default="2026_05")
    parser.add_argument("--call-count", type=int, default=2)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument(
        "--volume-scenario", choices=("observed", "low", "high"),
        default="observed",
    )
    parser.add_argument("--profile-id", default="pilot")
    parser.add_argument("--seed", type=int, default=700)
    parser.add_argument("--forecast-error", type=float, default=0.10)
    parser.add_argument("--minimum-free-factor", type=float, default=3.0)
    parser.add_argument("--selected-area-count", type=int)
    parser.add_argument("--oracle-time", type=float, default=60.0)
    parser.add_argument("--time-budget", type=float, default=60.0)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=base / "assembled_instances" / "pilot",
    )
    args = parser.parse_args()

    if args.volume_scenario == "observed":
        calls_path = args.attribute_root / "export_calls_model_ready.csv"
        groups_path = args.attribute_root / "export_groups_model_ready.csv"
    else:
        calls_path = args.attribute_root / "export_calls_scenarios.csv"
        groups_path = args.attribute_root / "export_groups_scenarios.csv"
    yard_dir = args.yard_root / args.yard_profile
    bays_path = yard_dir / "yard_bays.csv"
    inventory_path = yard_dir / "initial_locked_inventory.csv"

    all_calls = read_csv(calls_path)
    candidates = [
        row for row in all_calls
        if row["period"] == args.period
        and (
            args.volume_scenario == "observed"
            or row["scenario"] == args.volume_scenario
        )
        and (not args.start_date or row["entry_time"][:10] >= args.start_date)
        and (not args.end_date or row["entry_time"][:10] <= args.end_date)
    ]
    calls = sorted(
        candidates,
        key=lambda row: (row["entry_time"], row["call_id"]),
    )
    if args.call_count:
        calls = calls[: args.call_count]
    if args.call_count and len(calls) != args.call_count:
        raise ValueError("requested period does not contain enough export calls")
    if not calls:
        raise ValueError("selected source window contains no export calls")
    for row in calls:
        # Preserve the unchanged rolling adapter contract while retaining the
        # PNC-native names in the source files and bundle metadata.
        row["vessel_id"] = row.get("vessel_code", "")
        row["callsign"] = row.get("vessel_code", "")
        row["facility_name"] = row.get("berth", "")
    call_ids = {row["call_id"] for row in calls}
    groups = [
        row for row in read_csv(groups_path)
        if row["call_id"] in call_ids
        and (
            args.volume_scenario == "observed"
            or row["scenario"] == args.volume_scenario
        )
    ]
    incoming = sum(int(row["synthetic_export_boxes"]) for row in calls)
    bays, inventory, yard_scaling = select_yard(
        read_csv(bays_path),
        read_csv(inventory_path),
        incoming_boxes=incoming,
        minimum_free_factor=args.minimum_free_factor,
        selected_area_count=args.selected_area_count,
    )
    case, adapter_audit = build_portmis_rolling_case(
        calls,
        groups,
        seed=args.seed,
        forecast_error=args.forecast_error,
        forecast_error_mode="multiplicative",
        yard_bay_rows=bays,
        initial_inventory_rows=inventory,
    )
    certificate = solve_full_horizon_packing_oracle(
        case,
        release_basis="realized",
        time_limit=args.oracle_time,
        threads=1,
        seed=args.seed,
    )
    case["oracle_case_class"] = certificate["classification"]
    case["oracle_certificate"] = certificate
    case["instance_id"] = (
        f"pnc_yangshan_{args.profile_id}_{args.volume_scenario}_"
        f"n{len(calls)}_seed{args.seed}"
    )
    case["instance_family"] = "pnc_yangshan_observation_anchored_v2"
    case["instance_protocol"] = INSTANCE_PROTOCOL
    case["data_protocol_version"] = DATA_PROTOCOL
    if certificate["classification"] != "feasible":
        raise RuntimeError(
            "pilot failed integer packing certification: "
            f"{certificate['classification']}"
        )

    args.output_root.mkdir(parents=True, exist_ok=True)
    bundle_path = args.output_root / f"{case['instance_id']}.instance.json"
    metadata = {
        "instance_id": case["instance_id"],
        "instance_family": case["instance_family"],
        "instance_protocol": INSTANCE_PROTOCOL,
        "data_protocol_version": DATA_PROTOCOL,
        "seed": args.seed,
        "time_budget_seconds": args.time_budget,
        "source_period": args.period,
        "source_window": [args.start_date, args.end_date],
        "volume_scenario": args.volume_scenario,
        "source_terminal": "PNC / Busan New Port Pier 2",
        "yard_interpretation": "Yangshan OF-calibrated virtual yard",
        "yard_profile": args.yard_profile,
        "yard_scaling": yard_scaling,
        "forecast_error": args.forecast_error,
        "forecast_error_mode": "multiplicative",
        "calibration_validation_split": {
            "calibration": ["0508", "0519"],
            "held_out": ["0525"],
        },
        "excluded": [
            "PNC discharge boxes",
            "Yangshan voyage predictions",
            "import-discharge records",
            "45-foot containers",
            "non-OF yard areas",
        ],
        "source_hashes": {
            str(path.resolve().relative_to(ROOT)): sha256(path)
            for path in (
                calls_path,
                groups_path,
                bays_path,
                inventory_path,
                args.attribute_root / "manifest.json",
                args.yard_root / "manifest.json",
            )
        },
        "generator_git_commit": git_commit(),
        "adapter_audit": adapter_audit,
        "integer_packing_certificate": certificate,
    }
    identity = write_instance_bundle(bundle_path, case=case, metadata=metadata)
    audit = {
        "status": "PASS",
        "protocol_version": DATA_PROTOCOL,
        "bundle": identity,
        "selected_call_ids": sorted(call_ids),
        "generated_boxes_per_call": {
            row["call_id"]: int(row["synthetic_export_boxes"]) for row in calls
        },
        "joint_group_count": len(groups),
        "yard_scaling": yard_scaling,
        "readiness_gates": {
            "all_calls_from_pnc": all(row["demand_origin"].startswith("pnc_")
                                      for row in calls),
            "unique_calls": len(call_ids) == len(calls),
            "arrival_precedes_departure": all(
                row["entry_time"] < row["departure_time"] for row in calls
            ),
            "model_attributes_only": all(
                row["size_ft"] in {"20", "40"}
                and row["height_class"] in {"STD", "HIGH"}
                for row in groups
            ),
            "group_totals_reconcile": sum(int(row["boxes"]) for row in groups)
            == incoming,
            "integer_packing_feasible": certificate["classification"]
            == "feasible",
            "prediction_files_absent": True,
            "source_hashes_recorded": True,
        },
    }
    audit_path = args.output_root / "assembly_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "bundle": str(bundle_path),
        "audit": str(audit_path),
        "classification": certificate["classification"],
        "yard": yard_scaling,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Adapt calibrated PORT-MIS calls and run one bounded rolling-horizon case.

The adapter preserves the existing mathematical model and solver.  It replaces
only the synthetic ship schedule and demand baseline with the frozen
public-data-driven semi-synthetic layer produced by
``scripts/calibrate_portmis_demand.py``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    DEFAULT_OUTBOUND_BOXES_PER_6H,
    FORECAST_ERROR_MODES,
    LOOKAHEAD_HOURS,
    RECEIVING_WINDOW_HOURS,
    ROLLING_CYCLE_HOURS,
    TIME_BUCKET_HOURS,
    VALIDATE_EACH_EXECUTION_PERIOD,
)
from rolling_data import (  # noqa: E402
    build_initial_locked_inventory,
    forecast_trajectory_diagnostics,
    generate_forecast_trajectory,
    generate_hidden_truth,
)
from rolling_experiment import run_rolling_case  # noqa: E402


ADAPTER_PROTOCOL_VERSION = "portmis-rolling-adapter-v1"
SOLVER_STATUS_LABELS = {
    2: "OPTIMAL",
    9: "TIME_LIMIT",
    11: "INTERRUPTED",
}
DEFAULT_CALIBRATION_DIR = Path(
    "local_results/portmis_pilot_2025_07/calibrated_demand_v1"
)
PERIOD_HOURS = TIME_BUCKET_HOURS
EXECUTION_PERIODS = ROLLING_CYCLE_HOURS // PERIOD_HOURS
RECEIVING_PERIODS = RECEIVING_WINDOW_HOURS // PERIOD_HOURS
LOOKAHEAD_PERIODS = LOOKAHEAD_HOURS // PERIOD_HOURS


def _integer_profile(total: int, weights: Iterable[float]) -> list[int]:
    weights = list(weights)
    if total <= 0:
        return [0] * len(weights)
    denominator = sum(weights)
    if denominator <= 0:
        weights = [1.0] * len(weights)
        denominator = float(len(weights))
    raw = [total * weight / denominator for weight in weights]
    base = [math.floor(value) for value in raw]
    priority = sorted(
        range(len(raw)),
        key=lambda index: (-(raw[index] - base[index]), index),
    )
    for index in priority[: total - sum(base)]:
        base[index] += 1
    return base


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _floor_to_period(value: datetime) -> datetime:
    return value.replace(
        hour=(value.hour // PERIOD_HOURS) * PERIOD_HOURS,
        minute=0,
        second=0,
        microsecond=0,
    )


def _ceil_period(value: datetime, epoch: datetime) -> int:
    periods = (value - epoch).total_seconds() / (PERIOD_HOURS * 3600)
    return max(0, math.ceil(periods - 1e-12))


def _berth_number(facility_name: str) -> int:
    match = re.search(r"(\d+)\s*선석", facility_name)
    return int(match.group(1)) if match else 1


def _serial(value: object) -> object:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {
            "|".join(map(str, key)) if isinstance(key, tuple) else str(key): _serial(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_serial(item) for item in value]
    return value


def _validate_calibrated_rows(
    calls: Sequence[dict[str, str]],
    groups: Sequence[dict[str, str]],
) -> None:
    if not calls:
        raise ValueError("calibrated call demand is empty")
    call_ids = [row["call_id"] for row in calls]
    if len(call_ids) != len(set(call_ids)):
        raise ValueError("duplicate calibrated call_id")
    known = set(call_ids)
    if any(row["call_id"] not in known for row in groups):
        raise ValueError("group demand references an unknown call")
    call_totals = {
        row["call_id"]: int(row["synthetic_export_boxes"]) for row in calls
    }
    group_totals: dict[str, int] = {}
    for row in groups:
        quantity = int(row["boxes"])
        if quantity <= 0:
            raise ValueError("group demand must be a positive integer")
        if int(row["size_ft"]) not in (20, 40):
            raise ValueError("unsupported container size")
        if row["height_class"] not in ("STD", "HIGH"):
            raise ValueError("unsupported height class")
        key = row["call_id"]
        group_totals[key] = group_totals.get(key, 0) + quantity
    if call_totals != group_totals:
        raise ValueError(
            f"calibrated call/group totals do not reconcile: "
            f"calls={call_totals}, groups={group_totals}"
        )


def select_calibrated_calls(
    calls: Sequence[dict[str, str]],
    groups: Sequence[dict[str, str]],
    *,
    max_calls: int,
    selection_offset: int = 0,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Select consecutive real calls and their complete calibrated groups."""
    _validate_calibrated_rows(calls, groups)
    if max_calls <= 0 or selection_offset < 0:
        raise ValueError("max_calls must be positive and offset nonnegative")
    ordered = sorted(calls, key=lambda row: (row["entry_time"], row["call_id"]))
    selected = ordered[selection_offset : selection_offset + max_calls]
    if len(selected) < max_calls:
        raise ValueError("requested call slice exceeds calibrated snapshot")
    selected_ids = {row["call_id"] for row in selected}
    selected_groups = [
        row for row in groups if row["call_id"] in selected_ids
    ]
    _validate_calibrated_rows(selected, selected_groups)
    return selected, selected_groups


def select_calibrated_window(
    calls: Sequence[dict[str, str]],
    groups: Sequence[dict[str, str]],
    *,
    start_date: str,
    end_date: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Select a complete inclusive entry-date window without call truncation."""
    _validate_calibrated_rows(calls, groups)
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    if end < start:
        raise ValueError("end_date must not precede start_date")
    selected = sorted(
        (
            row
            for row in calls
            if start
            <= datetime.fromisoformat(row["entry_time"]).date()
            <= end
        ),
        key=lambda row: (row["entry_time"], row["call_id"]),
    )
    if not selected:
        raise ValueError("calibrated date window contains no calls")
    selected_ids = {row["call_id"] for row in selected}
    selected_groups = [
        row for row in groups if row["call_id"] in selected_ids
    ]
    _validate_calibrated_rows(selected, selected_groups)
    return selected, selected_groups


def build_portmis_rolling_case(
    calls: Sequence[dict[str, str]],
    groups: Sequence[dict[str, str]],
    *,
    seed: int = 700,
    num_blocks: int = 5,
    bays_per_block: int = 6,
    bay_capacity: int = 50,
    initial_utilization: float = 0.20,
    forecast_error: float = 0.10,
    forecast_error_mode: str = "multiplicative",
    nominal_outbound_rate_per_ship_period: int = (
        DEFAULT_OUTBOUND_BOXES_PER_6H
    ),
    yard_bay_rows: Sequence[dict[str, str]] | None = None,
    initial_inventory_rows: Sequence[dict[str, str]] | None = None,
) -> tuple[dict, dict]:
    """Map calibrated calls to the unchanged rolling-case data contract."""
    _validate_calibrated_rows(calls, groups)
    if forecast_error_mode not in FORECAST_ERROR_MODES:
        raise ValueError(f"unsupported forecast error mode: {forecast_error_mode}")
    if num_blocks <= 0 or bays_per_block <= 0 or bay_capacity <= 0:
        raise ValueError("yard dimensions must be positive")
    if not 0 <= initial_utilization <= 1:
        raise ValueError("initial utilization must be in [0, 1]")

    ordered_calls = sorted(
        calls, key=lambda row: (row["entry_time"], row["call_id"])
    )
    entries = [datetime.fromisoformat(row["entry_time"]) for row in ordered_calls]
    # Start one 6-hour period before the earliest 72-hour receiving window so
    # that the first observed call is admitted as a genuinely new ship.
    epoch = _floor_to_period(
        min(entries) - timedelta(hours=RECEIVING_WINDOW_HOURS)
    ) - timedelta(hours=PERIOD_HOURS)
    call_to_ship = {
        row["call_id"]: f"PV{index + 1:03d}"
        for index, row in enumerate(ordered_calls)
    }
    ship_to_call = {ship: call for call, ship in call_to_ship.items()}
    ships = [call_to_ship[row["call_id"]] for row in ordered_calls]

    eta_period: dict[str, int] = {}
    receiving_start: dict[str, int] = {}
    planned_release: dict[str, int] = {}
    realized_release: dict[str, int] = {}
    operation_duration: dict[str, int] = {}
    ship_class: dict[str, str] = {}
    source_schedule: dict[str, dict] = {}
    calibrated_totals = {
        call_to_ship[row["call_id"]]: int(row["synthetic_export_boxes"])
        for row in ordered_calls
    }
    for row in ordered_calls:
        ship = call_to_ship[row["call_id"]]
        entry = datetime.fromisoformat(row["entry_time"])
        departure = datetime.fromisoformat(row["departure_time"])
        eta = _ceil_period(entry, epoch)
        release = max(eta + 1, _ceil_period(departure, epoch))
        start = eta - RECEIVING_PERIODS
        if start <= 0:
            raise ValueError("adapter epoch failed to preserve new-ship admission")
        eta_period[ship] = eta
        receiving_start[ship] = start
        planned_release[ship] = release
        realized_release[ship] = release
        operation_duration[ship] = release - eta
        boxes = calibrated_totals[ship]
        ship_class[ship] = (
            "small" if boxes <= 400 else "medium" if boxes <= 1000 else "large"
        )
        source_schedule[ship] = {
            "call_id": row["call_id"],
            "vessel_id": row["vessel_id"],
            "callsign": row["callsign"],
            "vessel_name": row["vessel_name"],
            "facility_name": row["facility_name"],
            "entry_time": row["entry_time"],
            "departure_time": row["departure_time"],
            "receiving_start_period": start,
            "eta_period": eta,
            "release_period": release,
            "calibrated_export_boxes": boxes,
        }

    grouped_by_call: dict[str, list[dict[str, str]]] = {}
    for row in groups:
        grouped_by_call.setdefault(row["call_id"], []).append(row)
    group_attrs: dict[str, dict] = {}
    booking_flow: dict[tuple[str, str, int], int] = {}
    triangle = [1, 2, 3, 4, 5, 6, 6, 5, 4, 3, 2, 1]
    for call in ordered_calls:
        call_id = call["call_id"]
        ship = call_to_ship[call_id]
        for row in sorted(
            grouped_by_call[call_id],
            key=lambda item: (
                item["pod"],
                int(item["size_ft"]),
                item["height_class"],
            ),
        ):
            pod = row["pod"]
            size = int(row["size_ft"])
            height = row["height_class"]
            group = f"{pod}_{size}_{height}"
            attributes = {"pod": pod, "size": size, "height": height}
            if group in group_attrs and group_attrs[group] != attributes:
                raise ValueError(f"inconsistent attributes for group {group}")
            group_attrs[group] = attributes
            total = int(row["boxes"])
            profile = _integer_profile(total, triangle)
            for offset, quantity in enumerate(profile):
                if quantity:
                    key = (ship, group, receiving_start[ship] + offset)
                    booking_flow[key] = booking_flow.get(key, 0) + quantity

    cycles = max(
        1,
        math.ceil((max(planned_release.values()) + 1) / EXECUTION_PERIODS),
    )
    group_values = sorted(group_attrs)
    true_flow = generate_hidden_truth(
        booking_flow=booking_flow,
        forecast_error_mode=forecast_error_mode,
        error_level=forecast_error,
        seed=seed,
        receiving_start=receiving_start,
        eta_period=eta_period,
        groups=group_values,
    )
    true_total: dict[tuple[str, str], int] = {}
    for (ship, group, _absolute), quantity in true_flow.items():
        true_total[ship, group] = true_total.get((ship, group), 0) + quantity
    forecasts = generate_forecast_trajectory(
        true_flow=true_flow,
        booking_flow=booking_flow,
        cycles=cycles,
        forecast_error_mode=forecast_error_mode,
        error_level=forecast_error,
        seed=seed,
        receiving_start=receiving_start,
        eta_period=eta_period,
    )
    forecast_diagnostics = forecast_trajectory_diagnostics(
        forecasts=forecasts,
        true_flow=true_flow,
        cycles=cycles,
    )

    heights = ("STD", "HIGH")
    if yard_bay_rows is None:
        if initial_inventory_rows is not None:
            raise ValueError("initial_inventory_rows require yard_bay_rows")
        blocks = [f"B{index + 1:02d}" for index in range(num_blocks)]
        bays = [
            f"{block}_Y{position + 1:02d}"
            for block in blocks
            for position in range(bays_per_block)
        ]
        bay_block = {bay: bay.split("_Y")[0] for bay in bays}
        bay_size = {
            bay: 20 if index % 2 == 0 else 40
            for index, bay in enumerate(bays)
        }
        capacity = {bay: int(bay_capacity) for bay in bays}
        locked, locked_height, initialization_diagnostics = (
            build_initial_locked_inventory(
                bays=bays,
                capacity=capacity,
                bay_size=bay_size,
                heights=heights,
                target_utilization=initial_utilization,
                seed=seed,
            )
        )
        yard_source = "adapter_generated_regular_yard"
    else:
        if not yard_bay_rows:
            raise ValueError("yard_bay_rows must be nonempty")
        required = {"area", "bay", "size_ft", "capacity_boxes"}
        if any(not required.issubset(row) for row in yard_bay_rows):
            raise ValueError(f"yard_bay_rows require columns {sorted(required)}")
        bays = [row["bay"] for row in yard_bay_rows]
        if len(bays) != len(set(bays)):
            raise ValueError("yard_bay_rows contain duplicate bays")
        bay_block = {row["bay"]: row["area"] for row in yard_bay_rows}
        blocks = list(dict.fromkeys(row["area"] for row in yard_bay_rows))
        bay_size = {row["bay"]: int(row["size_ft"]) for row in yard_bay_rows}
        capacity = {
            row["bay"]: int(row["capacity_boxes"]) for row in yard_bay_rows
        }
        if set(bay_size.values()) - {20, 40}:
            raise ValueError("calibrated yard supports only 20/40-foot bays")
        if any(value <= 0 for value in capacity.values()):
            raise ValueError("calibrated yard capacity must be positive")
        inventory = list(initial_inventory_rows or [])
        inventory_required = {
            "bay", "old_ship", "locked_boxes", "height_class"
        }
        if any(not inventory_required.issubset(row) for row in inventory):
            raise ValueError(
                "initial_inventory_rows require bay, old_ship, locked_boxes, "
                "and height_class"
            )
        locked = {}
        locked_height = {}
        for row in inventory:
            bay = row["bay"]
            if bay not in capacity:
                continue
            height = row["height_class"]
            if height not in heights:
                raise ValueError(f"unsupported initial height class: {height}")
            key = (bay, row["old_ship"])
            quantity = int(row["locked_boxes"])
            if quantity <= 0:
                continue
            locked[key] = locked.get(key, 0) + quantity
            locked_height[key] = height
        per_bay_locked = {
            bay: sum(q for (candidate, _ship), q in locked.items()
                     if candidate == bay)
            for bay in bays
        }
        if any(per_bay_locked[bay] > capacity[bay] for bay in bays):
            raise ValueError("initial inventory exceeds calibrated bay capacity")
        total_capacity = sum(capacity.values())
        locked_quantity = sum(locked.values())
        initialization_diagnostics = {
            "requested_initial_utilization": (
                locked_quantity / total_capacity if total_capacity else 0.0
            ),
            "realized_initial_utilization": (
                locked_quantity / total_capacity if total_capacity else 0.0
            ),
            "initial_locked_quantity": locked_quantity,
            "initial_total_capacity": total_capacity,
            "initialization_shortfall": 0,
        }
        initial_utilization = initialization_diagnostics[
            "realized_initial_utilization"
        ]
        yard_source = "yangshan_of_calibrated_virtual_yard"

    distance: dict[tuple[str, str], int] = {}
    for row in ordered_calls:
        ship = call_to_ship[row["call_id"]]
        preferred = (_berth_number(row["facility_name"]) - 1) % len(blocks)
        for block_index, block in enumerate(blocks):
            distance[ship, block] = 100 + 120 * abs(block_index - preferred)

    old_release_period: dict[str, int] = {}
    old_outbound: dict[tuple[str, str, int], int] = {}
    for old_index, old_ship in enumerate(sorted({ship for _bay, ship in locked})):
        total = sum(
            quantity
            for (_bay, ship), quantity in locked.items()
            if ship == old_ship
        )
        duration = max(
            1, math.ceil(total / nominal_outbound_rate_per_ship_period)
        )
        start = old_index * EXECUTION_PERIODS
        old_release_period[old_ship] = start + duration
        block_remaining = {
            block: sum(
                quantity
                for (bay, ship), quantity in locked.items()
                if ship == old_ship and bay_block[bay] == block
            )
            for block in blocks
        }
        block_remaining = {
            block: quantity
            for block, quantity in block_remaining.items()
            if quantity
        }
        for offset, period_total in enumerate(
            _integer_profile(total, [1.0] * duration)
        ):
            left = period_total
            while left > 0 and block_remaining:
                block = min(
                    block_remaining,
                    key=lambda item: (-block_remaining[item], item),
                )
                take = min(left, block_remaining[block])
                old_outbound[old_ship, block, start + offset] = take
                block_remaining[block] -= take
                left -= take
                if block_remaining[block] <= 0:
                    del block_remaining[block]

    ship_outbound: dict[tuple[str, int], int] = {}
    for ship in ships:
        total = sum(
            quantity
            for (candidate, _group), quantity in true_total.items()
            if candidate == ship
        )
        duration = max(1, realized_release[ship] - eta_period[ship])
        for offset, quantity in enumerate(
            _integer_profile(total, [1.0] * duration)
        ):
            if quantity:
                ship_outbound[ship, eta_period[ship] + offset] = quantity

    outbound_forecasts: dict[tuple[int, str, str, int], int] = {}
    for cycle in range(cycles):
        now = cycle * EXECUTION_PERIODS
        for (old_ship, block, absolute), truth in old_outbound.items():
            if absolute >= now:
                outbound_forecasts[cycle, old_ship, block, absolute] = truth

    case = {
        "blocks": blocks,
        "bays": bays,
        "bay_block": bay_block,
        "bays_in_block": {
            block: [bay for bay in bays if bay_block[bay] == block]
            for block in blocks
        },
        "bay_size": bay_size,
        "capacity": capacity,
        "heights": heights,
        "ships": ships,
        "eta_period": eta_period,
        "receiving_start_period": receiving_start,
        "planned_ship_release_period": planned_release,
        "realized_ship_release_period": realized_release,
        "release_period_basis": "portmis_historical_schedule_deterministic_proxy",
        "ship_class": ship_class,
        "ship_operation_duration_periods": operation_duration,
        "release_delay_periods": 0,
        "group_attrs": group_attrs,
        "true_total": true_total,
        "true_flow": true_flow,
        "booking_flow": booking_flow,
        "forecast_generation_basis": (
            "calibrated_booking_baseline_hidden_truth_noisy_trajectory"
        ),
        "forecasts": forecasts,
        **forecast_diagnostics,
        "distance": distance,
        "locked_initial": locked,
        "locked_height_initial": locked_height,
        "old_release_period": old_release_period,
        "old_outbound_flow": old_outbound,
        "ship_outbound_flow": ship_outbound,
        "outbound_forecasts": outbound_forecasts,
        "outbound_boxes_per_period": nominal_outbound_rate_per_ship_period,
        "nominal_outbound_rate_per_ship_period": (
            nominal_outbound_rate_per_ship_period
        ),
        "cycles": cycles,
        "period_hours": PERIOD_HOURS,
        "execution_periods": EXECUTION_PERIODS,
        "receiving_periods": RECEIVING_PERIODS,
        "lookahead_periods": LOOKAHEAD_PERIODS,
        "seed": seed,
        "forecast_error": forecast_error,
        "forecast_error_mode": forecast_error_mode,
        "initial_utilization": initial_utilization,
        **initialization_diagnostics,
        "containers_per_ship_range": (
            min(calibrated_totals.values()),
            max(calibrated_totals.values()),
        ),
        "active_ship_overlap": len(ships),
        "pod_count": len({attributes["pod"] for attributes in group_attrs.values()}),
        "num_blocks": len(blocks),
        "bays_per_block": (
            bays_per_block if yard_bay_rows is None else None
        ),
        "num_ships": len(ships),
        "source_family": "portmis_capacity_anchored_semi_synthetic",
        "source_epoch": epoch.isoformat(timespec="minutes"),
        "call_to_ship": call_to_ship,
        "ship_to_call": ship_to_call,
        "source_schedule": source_schedule,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "yard_source": yard_source,
    }

    booking_by_ship = {
        ship: sum(
            quantity
            for (candidate, _group, _period), quantity in booking_flow.items()
            if candidate == ship
        )
        for ship in ships
    }
    receiving_lengths = {
        ship: eta_period[ship] - receiving_start[ship] for ship in ships
    }
    audit = {
        "adapter_status": "PASS",
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "source_family": case["source_family"],
        "selected_call_count": len(ordered_calls),
        "selected_call_ids": [row["call_id"] for row in ordered_calls],
        "source_epoch": case["source_epoch"],
        "real_to_model_mapping": {
            "entry_time": "eta_period",
            "entry_time_minus_72h": "receiving_start_period",
            "departure_time": "planned_and_realized_release_period",
            "facility_berth": "distance_preference_only",
            "calibrated_group_boxes": "booking_flow",
        },
        "semi_synthetic_fields": [
            "yard layout",
            "initial yard inventory",
            "forecast trajectory",
            "hidden realized receiving flow",
            "POD/size/height inherited from calibrated demand layer",
        ],
        "case_scale": {
            "cycles": cycles,
            "blocks": len(blocks),
            "yard_source": yard_source,
            "bays": len(bays),
            "capacity_slots": sum(capacity.values()),
            "initial_locked_boxes": sum(locked.values()),
            "calibrated_booking_boxes": sum(booking_flow.values()),
            "hidden_realized_boxes": sum(true_flow.values()),
            "groups": len(group_attrs),
        },
        "ship_lifecycle": source_schedule,
        "gates": {
            "calibrated_boxes_reconcile_to_booking_flow": all(
                booking_by_ship[ship] == calibrated_totals[ship] for ship in ships
            ),
            "receiving_window_is_72_hours": all(
                length == RECEIVING_PERIODS
                for length in receiving_lengths.values()
            ),
            "release_after_eta": all(
                planned_release[ship] > eta_period[ship] for ship in ships
            ),
            "all_calls_admitted_after_epoch": all(
                receiving_start[ship] > 0 for ship in ships
            ),
            "integer_booking_flow": all(
                isinstance(quantity, int) and quantity > 0
                for quantity in booking_flow.values()
            ),
            "case_covers_all_releases": (
                cycles * EXECUTION_PERIODS > max(realized_release.values())
            ),
        },
    }
    if not all(audit["gates"].values()):
        audit["adapter_status"] = "FAIL"
        failed = [key for key, value in audit["gates"].items() if not value]
        raise RuntimeError(f"PORT-MIS adapter audit failed: {failed}")
    return case, audit


def _render_report(adapter_audit: dict, result_summary: dict, gates: dict) -> str:
    scale = adapter_audit["case_scale"]
    gap = result_summary["mean_final_stage_mip_gap"]
    gap_text = str(gap) if gap is not None else "not available"
    gate_lines = "\n".join(
        f"- [{'x' if passed else ' '}] `{name}`" for name, passed in gates.items()
    )
    return f"""# PORT-MIS rolling end-to-end audit

Status: **{'PASS' if all(gates.values()) else 'FAIL'}**

Adapter protocol: `{adapter_audit['adapter_protocol_version']}`

## Case

- Selected real calls: {adapter_audit['selected_call_count']}
- Rolling cycles: {scale['cycles']}
- Yard: {scale['blocks']} blocks, {scale['bays']} bays,
  {scale['capacity_slots']} box slots
- Initial locked inventory: {scale['initial_locked_boxes']} boxes
- Calibrated booking demand: {scale['calibrated_booking_boxes']} boxes
- Hidden realized arrivals: {scale['hidden_realized_boxes']} boxes
- Attribute groups: {scale['groups']}

## Full algorithm result

- Configuration: `{result_summary['configuration']}`
- Solver cycles / skipped cycles:
  {result_summary['solver_cycles']} / {result_summary['skipped_cycles']}
- Total wall time: {result_summary['total_wall_time']:.3f} s
- Realized arrivals / unplaced:
  {result_summary['total_realized_arrivals']} /
  {result_summary['total_realized_unplaced']}
- Fallback placement quantity: {result_summary['total_fallback_placement_quantity']}
- Revision rate: {result_summary['revision_rate']:.6f}
- Validated solver cycles: {result_summary['validated_solver_cycles']}
- Final-stage status counts: {result_summary['final_stage_status_counts']}
- Progressive/bottleneck repair cycles:
  {result_summary['repair_triggered_cycles']} /
  {result_summary['bottleneck_repair_triggered_cycles']}
- Mean final-stage MIP gap: {gap_text}

## Gates

{gate_lines}

This is an integration smoke test, not a formal benchmark result.
"""


def run_end_to_end(
    *,
    calibration_dir: Path,
    output_dir: Path,
    max_calls: int,
    selection_offset: int,
    time_per_cycle: float,
    mip_gap: float,
    threads: int,
    seed: int,
    configuration: str,
    forecast_error: float,
    forecast_error_mode: str,
) -> tuple[dict, dict, dict]:
    calls_path = calibration_dir / "calibrated_call_demand.csv"
    groups_path = calibration_dir / "calibrated_group_demand.csv"
    calibration_audit_path = calibration_dir / "audit.json"
    for path in (calls_path, groups_path, calibration_audit_path):
        if not path.exists():
            raise FileNotFoundError(path)
    calibration_audit = _read_json(calibration_audit_path)
    if calibration_audit.get("calibration_status") != "PASS":
        raise ValueError("calibrated demand layer did not pass its audit")

    selected_calls, selected_groups = select_calibrated_calls(
        _read_csv(calls_path),
        _read_csv(groups_path),
        max_calls=max_calls,
        selection_offset=selection_offset,
    )
    case, adapter_audit = build_portmis_rolling_case(
        selected_calls,
        selected_groups,
        seed=seed,
        forecast_error=forecast_error,
        forecast_error_mode=forecast_error_mode,
    )
    adapter_audit["source_calibration"] = {
        "protocol_version": calibration_audit["protocol_version"],
        "calibration_directory": calibration_dir.as_posix(),
        "calls_sha256": _sha256(calls_path),
        "groups_sha256": _sha256(groups_path),
        "audit_sha256": _sha256(calibration_audit_path),
    }
    result = run_rolling_case(
        case,
        time_per_cycle=time_per_cycle,
        mip_gap=mip_gap,
        threads=threads,
        seed=seed,
        configuration=configuration,
    )
    solver_cycles = sum(not row.get("skipped", False) for row in result["cycles"])
    skipped_cycles = sum(row.get("skipped", False) for row in result["cycles"])
    solver_rows = [row for row in result["cycles"] if not row.get("skipped", False)]
    validated_solver_cycles = sum(
        bool((row.get("validation") or {}).get("feasible"))
        for row in solver_rows
    )
    final_stage_status_counts: dict[str, int] = {}
    for row in solver_rows:
        stages = row.get("stages") or []
        raw_status = stages[-1].get("status") if stages else None
        status = (
            f"{SOLVER_STATUS_LABELS.get(raw_status, 'STATUS')}({raw_status})"
            if raw_status is not None
            else "MISSING"
        )
        final_stage_status_counts[status] = (
            final_stage_status_counts.get(status, 0) + 1
        )
    repair_triggered_cycles = sum(
        bool(row.get("repair_triggered")) for row in solver_rows
    )
    bottleneck_repair_triggered_cycles = sum(
        bool(row.get("bottleneck_repair_triggered")) for row in solver_rows
    )
    final_actual_inventory = sum(
        result["final_state"].get("actual_inventory", {}).values()
    )
    final_locked_inventory = sum(
        result["final_state"].get("locked_inventory", {}).values()
    )
    summary = {
        "ok": result["ok"],
        "configuration": configuration,
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "source_calibration_protocol": calibration_audit["protocol_version"],
        "selected_call_count": len(selected_calls),
        "cycles": len(result["cycles"]),
        "solver_cycles": solver_cycles,
        "skipped_cycles": skipped_cycles,
        "validated_solver_cycles": validated_solver_cycles,
        "final_stage_status_counts": final_stage_status_counts,
        "repair_triggered_cycles": repair_triggered_cycles,
        "bottleneck_repair_triggered_cycles": (
            bottleneck_repair_triggered_cycles
        ),
        "total_wall_time": result["total_wall_time"],
        "total_solver_time": result["total_solver_time"],
        "total_realized_arrivals": result["total_realized_arrivals"],
        "total_realized_unplaced": result["total_realized_unplaced"],
        "unplaced_rate": result["unplaced_rate"],
        "total_fallback_placement_quantity": (
            result["total_fallback_placement_quantity"]
        ),
        "fallback_rate": result["fallback_rate"],
        "revision_rate": result["revision_rate"],
        "mean_final_stage_mip_gap": result["mean_final_stage_mip_gap"],
        "max_final_stage_mip_gap": result["max_final_stage_mip_gap"],
        "mean_nodes": result["mean_nodes"],
        "final_actual_inventory": final_actual_inventory,
        "final_locked_inventory": final_locked_inventory,
    }
    gates = {
        "calibration_audit_passed": (
            calibration_audit["calibration_status"] == "PASS"
        ),
        "adapter_audit_passed": adapter_audit["adapter_status"] == "PASS",
        "full_algorithm_completed": bool(result["ok"]),
        "all_realized_arrivals_placed": result["total_realized_unplaced"] == 0,
        "all_cycles_processed": len(result["cycles"]) == case["cycles"],
        "at_least_one_solver_cycle": solver_cycles > 0,
        "every_solver_solution_independently_validated": (
            validated_solver_cycles == solver_cycles
        ),
        "every_final_stage_has_solution": all(
            (row.get("stages") or [])
            and bool(row["stages"][-1].get("has_solution"))
            for row in solver_rows
        ),
        "all_hidden_arrivals_executed": (
            result["total_realized_arrivals"] == sum(case["true_flow"].values())
        ),
        "all_selected_ship_lifecycles_completed": (
            set(result["final_state"].get("completed", set()))
            == set(case["ships"])
        ),
        "final_ship_inventory_released": final_actual_inventory == 0,
        "final_old_inventory_released": final_locked_inventory == 0,
        "execution_period_validation_active": (
            VALIDATE_EACH_EXECUTION_PERIOD
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    adapter_path = output_dir / "adapter_audit.json"
    summary_path = output_dir / "summary.json"
    result_path = output_dir / "result.json"
    report_path = output_dir / "report.md"
    _write_json(adapter_path, adapter_audit)
    _write_json(summary_path, {"gates": gates, **summary})
    _write_json(result_path, _serial(result))
    report_path.write_text(
        _render_report(adapter_audit, summary, gates), encoding="utf-8"
    )
    manifest = {
        "adapter_protocol_version": ADAPTER_PROTOCOL_VERSION,
        "source_calibration": adapter_audit["source_calibration"],
        "run_parameters": {
            "max_calls": max_calls,
            "selection_offset": selection_offset,
            "time_per_cycle": time_per_cycle,
            "mip_gap": mip_gap,
            "threads": threads,
            "seed": seed,
            "configuration": configuration,
            "forecast_error": forecast_error,
            "forecast_error_mode": forecast_error_mode,
        },
        "outputs": {
            path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in (adapter_path, summary_path, result_path, report_path)
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    if not all(gates.values()):
        failed = [key for key, value in gates.items() if not value]
        raise RuntimeError(f"end-to-end audit failed: {failed}")
    return summary, adapter_audit, result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-dir", type=Path, default=DEFAULT_CALIBRATION_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "local_results/portmis_pilot_2025_07/end_to_end_small_v1"
        ),
    )
    parser.add_argument("--max-calls", type=int, default=3)
    parser.add_argument("--selection-offset", type=int, default=0)
    parser.add_argument("--time", type=float, default=5.0)
    parser.add_argument("--mip-gap", type=float, default=0.01)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=700)
    parser.add_argument("--configuration", default="full_bottleneck")
    parser.add_argument("--forecast-error", type=float, default=0.10)
    parser.add_argument(
        "--forecast-error-mode",
        choices=FORECAST_ERROR_MODES,
        default="multiplicative",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary, _adapter, _result = run_end_to_end(
        calibration_dir=args.calibration_dir,
        output_dir=args.output_dir,
        max_calls=args.max_calls,
        selection_offset=args.selection_offset,
        time_per_cycle=args.time,
        mip_gap=args.mip_gap,
        threads=args.threads,
        seed=args.seed,
        configuration=args.configuration,
        forecast_error=args.forecast_error,
        forecast_error_mode=args.forecast_error_mode,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

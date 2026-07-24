"""Build a capacity-anchored semi-synthetic demand layer from a PORT-MIS pilot.

This script intentionally does not alter the optimization model.  It converts
the frozen, real vessel-call snapshot into per-call export-yard box demand and
per-POD/size/height integer groups.  Fields unavailable from the public source
remain explicitly synthetic.

The default calibration is not claimed to be observed Sinsundae throughput:

* real call timing, identity, berth, gross tonnage, and route fields come from
  the PORT-MIS pilot snapshot;
* 2,236,000 TEU/year is the official Sinsundae design capacity;
* 2025 North Port import/export and total TEU are official aggregate figures;
* capacity utilization, the 50/50 import-export split, size mix, height mix,
  and per-container POD composition are transparent scenario assumptions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence


CALIBRATION_PROTOCOL_VERSION = "portmis-demand-v1"
DEFAULT_PILOT_DIR = Path("local_results/portmis_pilot_2025_07")

# Official public anchors.  URLs and interpretation are also written to every
# audit artifact so that a later actual-throughput source can replace them.
SINSUNDAE_CAPACITY_TEU_PER_YEAR = 2_236_000
NORTH_PORT_2025_TOTAL_TEU = 6_244_000
NORTH_PORT_2025_IMPORT_EXPORT_TEU = 4_056_000
BPA_CAPACITY_URL = (
    "https://www.busanpa.com/index.bpa?"
    "menuCd=DOM_000000103001003002"
)
BPA_THROUGHPUT_URL = (
    "https://www.busanpa.com/index.bpa?"
    "menuCd=DOM_000000105005001003"
)
CHAIN_PORTAL_URL = "https://www.chainportal.co.kr/main/"

REAL_CALL_FIELDS = (
    "call_id",
    "vessel_id",
    "callsign",
    "vessel_name",
    "entry_time",
    "departure_time",
    "gross_tonnage",
    "facility_name",
    "facility_cluster",
    "previous_port_country",
    "previous_port_code",
    "previous_port_name",
    "next_port_country",
    "next_port_code",
    "next_port_name",
)


@dataclass(frozen=True)
class CalibrationConfig:
    """Scenario assumptions for converting aggregate TEU to integer boxes."""

    design_capacity_teu_per_year: int = SINSUNDAE_CAPACITY_TEU_PER_YEAR
    capacity_utilization: float = 0.85
    import_export_split_to_export: float = 0.50
    forty_foot_box_share: float = 0.65
    high_cube_share_of_forty: float = 0.55
    min_boxes_per_call: int = 80
    max_boxes_per_call: int = 450
    boxes_per_pod: int = 100
    max_pods_per_call: int = 12

    @property
    def north_port_import_export_share(self) -> float:
        return NORTH_PORT_2025_IMPORT_EXPORT_TEU / NORTH_PORT_2025_TOTAL_TEU

    @property
    def modeled_export_teu_share(self) -> float:
        return (
            self.north_port_import_export_share
            * self.import_export_split_to_export
        )

    @property
    def mean_teu_per_box(self) -> float:
        return 1.0 + self.forty_foot_box_share

    def validate(self) -> None:
        if self.design_capacity_teu_per_year <= 0:
            raise ValueError("design capacity must be positive")
        for name in (
            "capacity_utilization",
            "import_export_split_to_export",
            "forty_foot_box_share",
            "high_cube_share_of_forty",
        ):
            value = getattr(self, name)
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.min_boxes_per_call < 0:
            raise ValueError("min_boxes_per_call must be nonnegative")
        if self.max_boxes_per_call < self.min_boxes_per_call:
            raise ValueError("max_boxes_per_call must not be below the minimum")
        if self.boxes_per_pod <= 0 or self.max_pods_per_call <= 0:
            raise ValueError("POD scaling parameters must be positive")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Sequence[dict], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _as_vector(value: int | Sequence[int], count: int) -> list[int]:
    if isinstance(value, int):
        return [value] * count
    result = list(value)
    if len(result) != count:
        raise ValueError("bound length does not match weight length")
    return result


def bounded_proportional_allocation(
    total: int,
    weights: Sequence[float],
    *,
    lower: int | Sequence[int] = 0,
    upper: int | Sequence[int],
    keys: Sequence[str] | None = None,
) -> list[int]:
    """Allocate an integer total by weights while respecting integer bounds."""
    count = len(weights)
    if count == 0:
        if total:
            raise ValueError("cannot allocate a positive total to no items")
        return []
    if any(weight < 0 or not math.isfinite(weight) for weight in weights):
        raise ValueError("weights must be finite and nonnegative")
    lower_values = _as_vector(lower, count)
    upper_values = _as_vector(upper, count)
    if any(low < 0 or high < low for low, high in zip(lower_values, upper_values)):
        raise ValueError("invalid allocation bounds")
    if not sum(lower_values) <= total <= sum(upper_values):
        raise ValueError(
            f"total {total} is outside feasible bounds "
            f"[{sum(lower_values)}, {sum(upper_values)}]"
        )

    labels = list(keys or [str(index) for index in range(count)])
    if len(labels) != count:
        raise ValueError("key length does not match weight length")
    values = list(lower_values)
    remaining = total - sum(values)
    active = {
        index for index in range(count) if values[index] < upper_values[index]
    }
    continuous = [0.0] * count

    while remaining and active:
        denominator = sum(weights[index] for index in active)
        if denominator <= 0:
            active_weights = {index: 1.0 for index in active}
            denominator = float(len(active))
        else:
            active_weights = {index: weights[index] for index in active}
        shares = {
            index: remaining * active_weights[index] / denominator
            for index in active
        }
        capped = [
            index
            for index in active
            if shares[index] >= upper_values[index] - values[index]
        ]
        if not capped:
            for index, share in shares.items():
                continuous[index] = share
            break
        for index in sorted(capped, key=lambda item: labels[item]):
            take = upper_values[index] - values[index]
            values[index] += take
            remaining -= take
            active.remove(index)

    for index in active:
        take = min(
            upper_values[index] - values[index],
            math.floor(continuous[index]),
        )
        values[index] += take
    residual = total - sum(values)
    priority = sorted(
        active,
        key=lambda index: (
            -(continuous[index] - math.floor(continuous[index])),
            labels[index],
        ),
    )
    while residual:
        progressed = False
        for index in priority:
            if values[index] >= upper_values[index]:
                continue
            values[index] += 1
            residual -= 1
            progressed = True
            if not residual:
                break
        if not progressed:
            raise RuntimeError("bounded integer allocation stalled")
    return values


def _period_days(scope: dict) -> int:
    start = date.fromisoformat(scope["start_date"])
    end = date.fromisoformat(scope["end_date"])
    days = (end - start).days + 1
    if days <= 0:
        raise ValueError("pilot end date precedes start date")
    return days


def _percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    left = math.floor(position)
    right = math.ceil(position)
    if left == right:
        return float(ordered[left])
    fraction = position - left
    return float(ordered[left] * (1 - fraction) + ordered[right] * fraction)


def _demand_targets(
    *,
    period_days: int,
    config: CalibrationConfig,
) -> dict[str, float | int]:
    capacity_period_teu = (
        config.design_capacity_teu_per_year * period_days / 365.0
    )
    modeled_export_teu = round(
        capacity_period_teu
        * config.capacity_utilization
        * config.modeled_export_teu_share
    )
    target_boxes = round(modeled_export_teu / config.mean_teu_per_box)
    target_forty_boxes = round(target_boxes * config.forty_foot_box_share)
    target_high_cube = round(
        target_forty_boxes * config.high_cube_share_of_forty
    )
    return {
        "period_days": period_days,
        "capacity_period_teu": capacity_period_teu,
        "modeled_export_teu_target": modeled_export_teu,
        "box_target": target_boxes,
        "forty_foot_box_target": target_forty_boxes,
        "high_cube_forty_box_target": target_high_cube,
    }


def _validate_source_rows(rows: Sequence[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("primary-cluster call snapshot is empty")
    call_ids = [row["call_id"] for row in rows]
    if len(call_ids) != len(set(call_ids)):
        raise ValueError("primary-cluster snapshot contains duplicate call_id values")
    for row in rows:
        missing = [field for field in REAL_CALL_FIELDS if not row.get(field)]
        if missing:
            raise ValueError(f"{row.get('call_id')}: missing fields {missing}")
        if row["facility_cluster"] != "SINSUNDAE":
            raise ValueError(f"{row['call_id']}: call is outside SINSUNDAE")
        if float(row["gross_tonnage"]) <= 0:
            raise ValueError(f"{row['call_id']}: gross tonnage must be positive")
        if datetime.fromisoformat(row["departure_time"]) < datetime.fromisoformat(
            row["entry_time"]
        ):
            raise ValueError(f"{row['call_id']}: departure precedes entry")


def calibrate_calls(
    rows: Sequence[dict[str, str]],
    *,
    period_days: int,
    config: CalibrationConfig,
) -> tuple[list[dict], list[dict], dict]:
    """Return per-call demand, integer attribute groups, and an audit payload."""
    config.validate()
    _validate_source_rows(rows)
    ordered = sorted(rows, key=lambda row: (row["entry_time"], row["call_id"]))
    targets = _demand_targets(period_days=period_days, config=config)
    box_target = int(targets["box_target"])
    count = len(ordered)
    if not (
        count * config.min_boxes_per_call
        <= box_target
        <= count * config.max_boxes_per_call
    ):
        raise ValueError(
            "aggregate box target is incompatible with per-call bounds: "
            f"target={box_target}, calls={count}, bounds="
            f"[{config.min_boxes_per_call}, {config.max_boxes_per_call}]"
        )

    # Gross tonnage is used only as a monotone capacity proxy.  Reported cargo
    # tonnage is intentionally excluded because it is neither container moves
    # nor the outbound export boxes represented by the model.
    gross_tonnages = [float(row["gross_tonnage"]) for row in ordered]
    call_boxes = bounded_proportional_allocation(
        box_target,
        gross_tonnages,
        lower=config.min_boxes_per_call,
        upper=config.max_boxes_per_call,
        keys=[row["call_id"] for row in ordered],
    )

    pod_buckets: list[dict] = []
    call_pod_counts: dict[str, int] = {}
    for row, boxes in zip(ordered, call_boxes):
        pod_count = min(
            config.max_pods_per_call,
            max(1, math.ceil(boxes / config.boxes_per_pod)),
        )
        pod_count = min(pod_count, boxes)
        call_pod_counts[row["call_id"]] = pod_count
        pod_weights = [1.0 / math.sqrt(index + 1) for index in range(pod_count)]
        pod_boxes = bounded_proportional_allocation(
            boxes,
            pod_weights,
            lower=1,
            upper=boxes,
            keys=[f"P{index + 1:02d}" for index in range(pod_count)],
        )
        for index, quantity in enumerate(pod_boxes):
            pod_buckets.append(
                {
                    "call_id": row["call_id"],
                    "pod": f"P{index + 1:02d}",
                    "boxes": quantity,
                }
            )

    bucket_keys = [
        f"{bucket['call_id']}:{bucket['pod']}" for bucket in pod_buckets
    ]
    bucket_totals = [int(bucket["boxes"]) for bucket in pod_buckets]
    forty_counts = bounded_proportional_allocation(
        int(targets["forty_foot_box_target"]),
        bucket_totals,
        lower=0,
        upper=bucket_totals,
        keys=bucket_keys,
    )
    high_counts = bounded_proportional_allocation(
        int(targets["high_cube_forty_box_target"]),
        forty_counts,
        lower=0,
        upper=forty_counts,
        keys=bucket_keys,
    )

    grouped_rows: list[dict] = []
    call_forty: dict[str, int] = {}
    call_high: dict[str, int] = {}
    for bucket, forty, high in zip(pod_buckets, forty_counts, high_counts):
        twenty = int(bucket["boxes"]) - forty
        forty_standard = forty - high
        quantities = (
            (20, "STD", twenty),
            (40, "STD", forty_standard),
            (40, "HIGH", high),
        )
        for size, height, quantity in quantities:
            if quantity <= 0:
                continue
            grouped_rows.append(
                {
                    "call_id": bucket["call_id"],
                    "pod": bucket["pod"],
                    "size_ft": size,
                    "height_class": height,
                    "boxes": quantity,
                    "teu": quantity * (size // 20),
                    "field_origin": "semi_synthetic",
                }
            )
        call_forty[bucket["call_id"]] = (
            call_forty.get(bucket["call_id"], 0) + forty
        )
        call_high[bucket["call_id"]] = (
            call_high.get(bucket["call_id"], 0) + high
        )

    per_call_rows: list[dict] = []
    for row, boxes, gross_tonnage in zip(ordered, call_boxes, gross_tonnages):
        forty = call_forty.get(row["call_id"], 0)
        high = call_high.get(row["call_id"], 0)
        output = {field: row[field] for field in REAL_CALL_FIELDS}
        output.update(
            {
                "synthetic_export_boxes": boxes,
                "synthetic_export_teu": boxes + forty,
                "synthetic_pod_count": call_pod_counts[row["call_id"]],
                "synthetic_20ft_boxes": boxes - forty,
                "synthetic_40ft_boxes": forty,
                "synthetic_40ft_high_cube_boxes": high,
                "gross_tonnage_weight_share": (
                    gross_tonnage / sum(gross_tonnages)
                ),
                "demand_origin": "capacity_anchored_semi_synthetic",
            }
        )
        per_call_rows.append(output)

    total_boxes = sum(row["synthetic_export_boxes"] for row in per_call_rows)
    total_teu = sum(row["synthetic_export_teu"] for row in per_call_rows)
    total_forty = sum(row["synthetic_40ft_boxes"] for row in per_call_rows)
    total_high = sum(
        row["synthetic_40ft_high_cube_boxes"] for row in per_call_rows
    )
    group_boxes = sum(row["boxes"] for row in grouped_rows)
    group_teu = sum(row["teu"] for row in grouped_rows)
    per_call_box_values = [
        row["synthetic_export_boxes"] for row in per_call_rows
    ]
    pod_values = [row["synthetic_pod_count"] for row in per_call_rows]
    audit = {
        "calibration_status": "PASS",
        "protocol_version": CALIBRATION_PROTOCOL_VERSION,
        "information_boundary": {
            "real_fields": list(REAL_CALL_FIELDS),
            "semi_synthetic_fields": [
                "export boxes per call",
                "container POD",
                "container size",
                "container height",
            ],
            "explicitly_unused_source_fields": [
                "inbound_loaded_cargo_tonnage",
                "outbound_loaded_cargo_tonnage",
            ],
        },
        "official_anchors": {
            "sinsundae_design_capacity_teu_per_year": (
                config.design_capacity_teu_per_year
            ),
            "north_port_2025_total_teu": NORTH_PORT_2025_TOTAL_TEU,
            "north_port_2025_import_export_teu": (
                NORTH_PORT_2025_IMPORT_EXPORT_TEU
            ),
            "north_port_2025_import_export_share": (
                config.north_port_import_export_share
            ),
            "capacity_source": BPA_CAPACITY_URL,
            "throughput_source": BPA_THROUGHPUT_URL,
            "fine_statistics_portal": CHAIN_PORTAL_URL,
            "fine_statistics_access_note": (
                "Chain Portal detailed statistics require an authentication "
                "token; no anonymous terminal-month actual was used."
            ),
        },
        "scenario_assumptions": asdict(config),
        "derived_targets": targets,
        "results": {
            "call_count": len(per_call_rows),
            "group_row_count": len(grouped_rows),
            "allocated_boxes": total_boxes,
            "allocated_teu": total_teu,
            "allocated_20ft_boxes": total_boxes - total_forty,
            "allocated_40ft_boxes": total_forty,
            "allocated_40ft_high_cube_boxes": total_high,
            "box_per_call_min": min(per_call_box_values),
            "box_per_call_median": statistics.median(per_call_box_values),
            "box_per_call_p90": _percentile(per_call_box_values, 0.90),
            "box_per_call_max": max(per_call_box_values),
            "pod_per_call_min": min(pod_values),
            "pod_per_call_median": statistics.median(pod_values),
            "pod_per_call_max": max(pod_values),
            "realized_40ft_box_share": total_forty / total_boxes,
            "realized_high_cube_share_of_forty": total_high / total_forty,
        },
        "gates": {
            "per_call_boxes_reconcile_to_target": total_boxes == box_target,
            "group_boxes_reconcile_to_calls": group_boxes == total_boxes,
            "group_teu_reconcile_to_calls": group_teu == total_teu,
            "forty_foot_target_exact": (
                total_forty == targets["forty_foot_box_target"]
            ),
            "high_cube_target_exact": (
                total_high == targets["high_cube_forty_box_target"]
            ),
            "all_group_quantities_positive_integer": all(
                isinstance(row["boxes"], int) and row["boxes"] > 0
                for row in grouped_rows
            ),
            "per_call_bounds_respected": all(
                config.min_boxes_per_call
                <= value
                <= config.max_boxes_per_call
                for value in per_call_box_values
            ),
            "twenty_foot_high_cube_excluded_in_baseline": all(
                not (
                    row["size_ft"] == 20
                    and row["height_class"] == "HIGH"
                )
                for row in grouped_rows
            ),
        },
        "limitations": [
            (
                "The result is capacity-anchored semi-synthetic demand, not "
                "observed terminal-month or per-vessel throughput."
            ),
            (
                "The North Port aggregate mix is a proxy for Sinsundae; the "
                "50/50 import-export split is a scenario assumption."
            ),
            (
                "Gross tonnage supplies only relative call weights and does "
                "not reveal actual container moves."
            ),
            (
                "POD, size, and height composition must be varied in formal "
                "sensitivity experiments."
            ),
        ],
    }
    if not all(audit["gates"].values()):
        audit["calibration_status"] = "FAIL"
        failed = [name for name, passed in audit["gates"].items() if not passed]
        raise RuntimeError(f"calibration audit failed: {failed}")
    return per_call_rows, grouped_rows, audit


def _render_report(audit: dict) -> str:
    results = audit["results"]
    targets = audit["derived_targets"]
    assumptions = audit["scenario_assumptions"]
    gates = audit["gates"]
    gate_lines = "\n".join(
        f"- [{'x' if passed else ' '}] `{name}`" for name, passed in gates.items()
    )
    return f"""# PORT-MIS demand calibration audit

Status: **{audit['calibration_status']}**

Protocol: `{audit['protocol_version']}`

## Interpretation

This artifact is a **capacity-anchored semi-synthetic** demand layer. It does
not claim that the generated boxes are observed Sinsundae throughput. Real
PORT-MIS call fields are retained, while export box volume and container
attributes are generated under the assumptions recorded in `audit.json`.

## Aggregate calibration

- Period: {targets['period_days']} days
- Official design-capacity equivalent: {targets['capacity_period_teu']:.2f} TEU
- Assumed capacity utilization: {assumptions['capacity_utilization']:.2%}
- Modeled export share of terminal TEU: {audit['official_anchors']['north_port_2025_import_export_share'] * assumptions['import_export_split_to_export']:.2%}
- Target export TEU: {targets['modeled_export_teu_target']:,}
- Generated boxes / TEU: {results['allocated_boxes']:,} / {results['allocated_teu']:,}
- Calls / attribute rows: {results['call_count']:,} / {results['group_row_count']:,}

## Per-call scale

- Boxes min / median / p90 / max:
  {results['box_per_call_min']:.0f} / {results['box_per_call_median']:.1f} /
  {results['box_per_call_p90']:.1f} / {results['box_per_call_max']:.0f}
- POD count min / median / max:
  {results['pod_per_call_min']:.0f} / {results['pod_per_call_median']:.1f} /
  {results['pod_per_call_max']:.0f}
- Realized 40-foot box share: {results['realized_40ft_box_share']:.2%}
- Realized high-cube share among 40-foot boxes:
  {results['realized_high_cube_share_of_forty']:.2%}

## Audit gates

{gate_lines}

## Required paper wording

Describe this family as public-data-driven semi-synthetic instances. Cite
PORT-MIS for vessel calls and BPA for aggregate capacity/statistics. Do not
describe the generated per-call volumes, PODs, sizes, or heights as observed
terminal records.
"""


def run(pilot_dir: Path, output_dir: Path, config: CalibrationConfig) -> dict:
    source_calls = pilot_dir / "primary_cluster_calls.csv"
    source_audit = pilot_dir / "audit.json"
    if not source_calls.exists() or not source_audit.exists():
        raise FileNotFoundError(
            "pilot directory must contain primary_cluster_calls.csv and audit.json"
        )
    pilot_audit = _read_json(source_audit)
    scope = pilot_audit["scope"]
    if scope.get("primary_cluster") != "SINSUNDAE":
        raise ValueError("this calibration profile expects SINSUNDAE")
    rows = _read_csv(source_calls)
    calls, groups, audit = calibrate_calls(
        rows,
        period_days=_period_days(scope),
        config=config,
    )
    audit["source_snapshot"] = {
        "pilot_directory": pilot_dir.as_posix(),
        "primary_cluster_calls_sha256": _sha256(source_calls),
        "pilot_audit_sha256": _sha256(source_audit),
        "scope": scope,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    calls_path = output_dir / "calibrated_call_demand.csv"
    groups_path = output_dir / "calibrated_group_demand.csv"
    audit_path = output_dir / "audit.json"
    report_path = output_dir / "report.md"
    _write_csv(calls_path, calls, list(calls[0]))
    _write_csv(groups_path, groups, list(groups[0]))
    _write_json(audit_path, audit)
    report_path.write_text(_render_report(audit), encoding="utf-8")

    manifest = {
        "protocol_version": CALIBRATION_PROTOCOL_VERSION,
        "created_by": "scripts/calibrate_portmis_demand.py",
        "source": audit["source_snapshot"],
        "outputs": {
            path.name: {"sha256": _sha256(path), "bytes": path.stat().st_size}
            for path in (calls_path, groups_path, audit_path, report_path)
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    return audit


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=DEFAULT_PILOT_DIR)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_PILOT_DIR / "calibrated_demand_v1",
    )
    parser.add_argument("--capacity-utilization", type=float, default=0.85)
    parser.add_argument("--export-split", type=float, default=0.50)
    parser.add_argument("--forty-foot-share", type=float, default=0.65)
    parser.add_argument("--high-cube-share", type=float, default=0.55)
    parser.add_argument("--min-boxes-per-call", type=int, default=80)
    parser.add_argument("--max-boxes-per-call", type=int, default=450)
    parser.add_argument("--boxes-per-pod", type=int, default=100)
    parser.add_argument("--max-pods-per-call", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = CalibrationConfig(
        capacity_utilization=args.capacity_utilization,
        import_export_split_to_export=args.export_split,
        forty_foot_box_share=args.forty_foot_share,
        high_cube_share_of_forty=args.high_cube_share,
        min_boxes_per_call=args.min_boxes_per_call,
        max_boxes_per_call=args.max_boxes_per_call,
        boxes_per_pod=args.boxes_per_pod,
        max_pods_per_call=args.max_pods_per_call,
    )
    audit = run(args.pilot_dir, args.output_dir, config)
    print(
        json.dumps(
            {
                "status": audit["calibration_status"],
                "output_dir": args.output_dir.as_posix(),
                "calls": audit["results"]["call_count"],
                "boxes": audit["results"]["allocated_boxes"],
                "teu": audit["results"]["allocated_teu"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

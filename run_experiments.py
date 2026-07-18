"""Controlled rolling experiments with non-overlapping realized metrics."""
from __future__ import annotations

import argparse
import csv
import json

from main import PRESETS
from rolling_data import build_repair_pressure_case, build_synthetic_rolling_case
from rolling_experiment import run_rolling_case
from rolling_solver import CONFIGURATIONS


def stage_summary(result: dict) -> dict:
    stages = [stage for cycle in result["cycles"] for stage in cycle.get("stages", [])]
    first = [stage["first_incumbent_time"] for stage in stages if stage.get("first_incumbent_time") is not None]
    return {
        "repair_expansions": sum(cycle.get("repair_expansions", 0) for cycle in result["cycles"]),
        "budget_binding_stages": sum(bool(stage.get("stability_budget_binding")) for stage in stages),
        "max_variables": max((stage["variables"] for stage in stages), default=0),
        "max_constraints": max((stage["constraints"] for stage in stages), default=0),
        "mean_first_incumbent_time": sum(first) / len(first) if first else None,
    }


def result_row(instance: str, forecast_error: float, outbound_rate: int, configuration: str, seed: int, result: dict) -> dict:
    predicted = [
        (cycle.get("forecast_diagnostics") or {}).get("predicted_shortage")
        for cycle in result["cycles"]
    ]
    predicted = [value for value in predicted if value is not None]
    return {
        "instance": instance,
        "forecast_error": forecast_error,
        "outbound_rate": outbound_rate,
        "configuration": configuration,
        "seed": seed,
        "ok": result["ok"],
        "cycles": len(result["cycles"]),
        "runtime": result["total_runtime"],
        "realized_arrivals": result["total_realized_arrivals"],
        "planned_placement": result["total_planned_placement_quantity"],
        "fallback_placement": result["total_fallback_placement_quantity"],
        "realized_unplaced": result["total_realized_unplaced"],
        "realized_distance": result["total_realized_distance"],
        "realized_in_out_conflict": result["total_realized_in_out_conflict"],
        "cancellation_quantity": result["total_cancellation_quantity"],
        "mandatory_reduction": result["total_mandatory_reduction"],
        "discretionary_cancel": result["total_discretionary_cancel"],
        "new_bay_count": result["total_new_bay_count"],
        "block_reallocation_quantity": result["total_block_reallocation_quantity"],
        "stability_cost": result["total_stability_cost"],
        "mean_cycle_predicted_shortage": sum(predicted) / len(predicted) if predicted else None,
        "max_cycle_predicted_shortage": max(predicted) if predicted else None,
        **stage_summary(result),
        "stages": json.dumps([cycle.get("final_stage") for cycle in result["cycles"]]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", choices=PRESETS, default=list(PRESETS))
    parser.add_argument("--errors", nargs="+", type=float, default=[0, .1, .2])
    parser.add_argument("--configurations", nargs="+", choices=CONFIGURATIONS, default=["full"])
    parser.add_argument("--pressure-levels", nargs="*", choices=("nearby", "global"), default=[])
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--time", type=float, default=20)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--outbound-rate", type=int, default=150)
    parser.add_argument("--output", default="rolling_results.csv")
    args = parser.parse_args()
    rows = []
    for size in args.sizes:
        for error in args.errors:
            for seed in args.seeds:
                for configuration in args.configurations:
                    case = build_synthetic_rolling_case(
                        seed=seed,
                        forecast_error=error,
                        outbound_boxes_per_period=args.outbound_rate,
                        **PRESETS[size],
                    )
                    result = run_rolling_case(
                        case,
                        time_per_cycle=args.time,
                        threads=args.threads,
                        seed=seed,
                        configuration=configuration,
                    )
                    row = result_row(size, error, args.outbound_rate, configuration, seed, result)
                    rows.append(row)
                    print(row, flush=True)
    for level in args.pressure_levels:
        for seed in args.seeds:
            case = build_repair_pressure_case(level=level, seed=seed)
            result = run_rolling_case(
                case,
                time_per_cycle=args.time,
                threads=args.threads,
                seed=seed,
                configuration="full",
            )
            row = result_row(
                f"pressure_{level}", .1, case["outbound_boxes_per_period"], "full", seed, result
            )
            rows.append(row)
            print(row, flush=True)
    with open(args.output, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return 0 if all(row["ok"] for row in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())

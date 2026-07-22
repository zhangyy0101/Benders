"""CLI for the stability-aware rolling bay-level allocation framework."""
from __future__ import annotations

import argparse
import json

from config import DEPENDENCY_PROFILES, FORECAST_ERROR_MODES
from rolling_data import build_repair_pressure_case, build_synthetic_rolling_case
from rolling_experiment import run_rolling_case
from rolling_solver import CONFIGURATIONS

PRESETS = {
    "pilot_small": dict(
        num_blocks=3,
        bays_per_block=4,
        num_ships=3,
        cycles=3,
        containers_per_ship_range=(40, 80),
        active_ship_overlap=2,
        pod_count=2,
    ),
    "pilot_medium": dict(
        num_blocks=5,
        bays_per_block=5,
        num_ships=6,
        cycles=4,
        containers_per_ship_range=(80, 160),
        active_ship_overlap=2,
        pod_count=4,
    ),
    "small": dict(
        num_blocks=4,
        bays_per_block=6,
        num_ships=5,
        cycles=5,
        containers_per_ship_range=(60, 120),
        active_ship_overlap=2,
        pod_count=3,
    ),
    "medium": dict(
        num_blocks=8,
        bays_per_block=8,
        num_ships=10,
        cycles=6,
        containers_per_ship_range=(120, 300),
        active_ship_overlap=3,
        pod_count=5,
    ),
    "large": dict(
        num_blocks=12,
        bays_per_block=10,
        num_ships=16,
        cycles=8,
        containers_per_ship_range=(250, 600),
        active_ship_overlap=4,
        pod_count=8,
    ),
    "xlarge": dict(
        num_blocks=20,
        bays_per_block=10,
        num_ships=25,
        cycles=10,
        containers_per_ship_range=(400, 1000),
        active_ship_overlap=5,
        pod_count=10,
    ),
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Rolling bay-level allocation")
    result.add_argument("--size", choices=PRESETS, default="small")
    result.add_argument("--configuration", choices=CONFIGURATIONS, default="full")
    result.add_argument("--pressure", choices=("nearby", "global"))
    result.add_argument("--time", type=float, default=20, help="wall-clock seconds per cycle")
    result.add_argument("--forecast-error", type=float, default=.10)
    result.add_argument(
        "--forecast-error-mode",
        choices=FORECAST_ERROR_MODES,
        default="multiplicative",
    )
    result.add_argument("--initial-utilization", type=float, default=.25)
    result.add_argument(
        "--outbound-rate",
        type=int,
        default=150,
        help="boxes per ship per 6-hour period",
    )
    result.add_argument("--release-delay-periods", type=int, default=0)
    result.add_argument("--seed", type=int, default=0)
    result.add_argument("--threads", type=int, default=1)
    result.add_argument("--mip-gap", type=float, default=.01)
    result.add_argument(
        "--dependency-profile",
        choices=DEPENDENCY_PROFILES,
        default="current",
    )
    result.add_argument("--output")
    return result


def serial(value: object) -> object:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {
            "|".join(map(str, key)) if isinstance(key, tuple) else str(key): serial(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [serial(item) for item in value]
    return value


def main() -> int:
    args = parser().parse_args()
    if args.pressure:
        case = build_repair_pressure_case(level=args.pressure, seed=args.seed)
    else:
        case = build_synthetic_rolling_case(
            seed=args.seed,
            forecast_error=args.forecast_error,
            forecast_error_mode=args.forecast_error_mode,
            initial_utilization=args.initial_utilization,
            nominal_outbound_rate_per_ship_period=args.outbound_rate,
            release_delay_periods=args.release_delay_periods,
            **PRESETS[args.size],
        )
    result = run_rolling_case(
        case,
        time_per_cycle=args.time,
        mip_gap=args.mip_gap,
        threads=args.threads,
        seed=args.seed,
        configuration=args.configuration,
        dependency_profile=args.dependency_profile,
    )
    summary = {key: value for key, value in result.items() if key != "final_state"}
    print(json.dumps(serial(summary), indent=2, ensure_ascii=False))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            json.dump(serial(result), stream, indent=2, ensure_ascii=False)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

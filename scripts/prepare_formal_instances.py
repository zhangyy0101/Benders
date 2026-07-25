"""Prepare immutable synthetic or PORT-MIS instance bundles before solving."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    FORECAST_ERROR_MODES,
    FORMAL_PUBLIC_CALIBRATION_SCENARIOS,
    FORMAL_SEEDS,
    FORMAL_SYNTHETIC_SCALE_INITIAL_UTILIZATION,
    FORMAL_SYNTHETIC_PRESSURE_TARGET_TOLERANCE,
    FORMAL_SYNTHETIC_PRESSURE_TARGETS,
    FORMAL_SYNTHETIC_UTILIZATION_LEVELS,
    FORMAL_SYNTHETIC_UTILIZATION_SHIP_VOLUME_FACTOR,
    FORMAL_SYNTHETIC_UTILIZATION_SIZE,
    FORMAL_TIME_BUDGETS_SECONDS,
    FORMAL_PUBLIC_TEMPORAL_WINDOWS,
    FORMAL_PUBLIC_WINDOWS,
    SYNTHETIC_PRESSURE_PROTOCOL,
)
from experiment_metadata import collect_git_metadata  # noqa: E402
from formal_experiments import (  # noqa: E402
    INSTANCE_PROTOCOL,
    build_portmis_window_case,
    case_sha256,
    read_instance_bundle,
    write_instance_bundle,
)
from main import PRESETS  # noqa: E402
from rolling_data import (  # noqa: E402
    aggregate_size_period_pressure_diagnostics,
    build_integer_certified_pressure_case_family,
    build_oracle_certified_case_family,
    build_repair_pressure_case,
    build_synthetic_rolling_case,
)


def _instance_path(output_dir: Path, instance_id: str) -> Path:
    return output_dir / f"{instance_id}.instance.json"


def _archive(
    output_dir: Path,
    *,
    case: dict,
    metadata: dict[str, object],
    overwrite: bool,
) -> dict[str, object]:
    path = _instance_path(output_dir, str(metadata["instance_id"]))
    if path.exists() and not overwrite:
        archived_case, archived_metadata = read_instance_bundle(path)
        if case_sha256(archived_case) != case_sha256(case):
            raise ValueError(
                f"existing bundle differs from regenerated case: {path}"
            )
        comparable = {
            key: value
            for key, value in metadata.items()
            if key not in {"generator_git_commit", "generator_git_branch"}
        }
        archived_comparable = {
            key: archived_metadata.get(key) for key in comparable
        }
        if comparable != archived_comparable:
            raise ValueError(
                f"existing bundle metadata differs from request: {path}"
            )
        return archived_metadata
    return write_instance_bundle(path, case=case, metadata=metadata)


def _synthetic_instances(args: argparse.Namespace) -> list[dict[str, object]]:
    git = collect_git_metadata()
    entries: list[dict[str, object]] = []
    for size in args.sizes:
        for seed in args.seeds:
            case_kwargs = {
                **dict(PRESETS[size]),
                "seed": seed,
                "forecast_error": args.forecast_error,
                "forecast_error_mode": args.forecast_error_mode,
                "initial_utilization": args.initial_utilization,
                "nominal_outbound_rate_per_ship_period": args.outbound_rate,
                "release_delay_periods": args.release_delay_periods,
            }
            if args.capacity_pressure_profiles:
                family = build_integer_certified_pressure_case_family(
                    pressure_targets={
                        label: FORMAL_SYNTHETIC_PRESSURE_TARGETS[label]
                        for label in args.capacity_pressure_profiles
                    },
                    factor_bounds=tuple(args.oracle_factor_bounds),
                    target_absolute_tolerance=args.pressure_target_tolerance,
                    search_iterations=args.pressure_search_iterations,
                    oracle_time_limit=args.oracle_time,
                    oracle_threads=args.oracle_threads,
                    oracle_seed=seed,
                    **case_kwargs,
                )
                cases = [
                    (f"{size}_{label}", family[label])
                    for label in args.capacity_pressure_profiles
                ]
            elif args.oracle_case_classes:
                family = build_oracle_certified_case_family(
                    factor_bounds=tuple(args.oracle_factor_bounds),
                    search_iterations=args.oracle_search_iterations,
                    oracle_time_limit=args.oracle_time,
                    oracle_threads=args.oracle_threads,
                    oracle_seed=seed,
                    **case_kwargs,
                )
                cases = [
                    (f"{size}_{label}", family[label])
                    for label in args.oracle_case_classes
                ]
            else:
                case = build_synthetic_rolling_case(
                    ship_volume_factor=args.ship_volume_factor,
                    **case_kwargs,
                )
                if args.certify_oracle:
                    from rolling_model import solve_full_horizon_packing_oracle

                    diagnostics = aggregate_size_period_pressure_diagnostics(
                        case
                    )
                    certificate = solve_full_horizon_packing_oracle(
                        case,
                        release_basis="realized",
                        time_limit=args.oracle_time,
                        threads=args.oracle_threads,
                        seed=seed,
                    )
                    if certificate["classification"] != "feasible":
                        raise RuntimeError(
                            "certified formal comparison cases require a "
                            "zero-shortage integer packing certificate; "
                            f"classification={certificate['classification']}"
                        )
                    case["capacity_pressure_profile"] = "observed"
                    case["capacity_pressure_target"] = None
                    case["capacity_pressure_diagnostics"] = diagnostics
                    case["oracle_case_class"] = certificate["classification"]
                    case["oracle_certificate"] = dict(certificate)
                cases = [(size, case)]
            for profile, case in cases:
                instance_id = (
                    f"synthetic_{profile}_e{args.forecast_error:g}_"
                    f"{args.forecast_error_mode}_u{args.initial_utilization:g}_"
                    f"seed{seed}"
                )
                case.update({
                    "instance_id": instance_id,
                    "instance_family": "reproducible_synthetic",
                    "instance_protocol": INSTANCE_PROTOCOL,
                    "synthetic_pressure_protocol": (
                        SYNTHETIC_PRESSURE_PROTOCOL
                    ),
                })
                metadata = {
                    "instance_id": instance_id,
                    "instance_family": case["instance_family"],
                    "instance_protocol": INSTANCE_PROTOCOL,
                    "synthetic_pressure_protocol": (
                        SYNTHETIC_PRESSURE_PROTOCOL
                    ),
                    "profile": profile,
                    "seed": seed,
                    "time_budget_seconds": FORMAL_TIME_BUDGETS_SECONDS[size],
                    "forecast_error": args.forecast_error,
                    "forecast_error_mode": args.forecast_error_mode,
                    "initial_utilization": args.initial_utilization,
                    "oracle_case_class": case.get(
                        "oracle_case_class", "not_evaluated"
                    ),
                    "capacity_pressure_profile": case.get(
                        "capacity_pressure_profile", "not_evaluated"
                    ),
                    "capacity_pressure_target": case.get(
                        "capacity_pressure_target"
                    ),
                    "capacity_pressure_peak_load_ratio": case.get(
                        "capacity_pressure_diagnostics", {}
                    ).get("peak_load_ratio"),
                    "generator_git_commit": git.get("git_commit"),
                    "generator_git_branch": git.get("git_branch"),
                    "source_publication_ready": None,
                }
                entries.append(_archive(
                    args.output_dir,
                    case=case,
                    metadata=metadata,
                    overwrite=args.overwrite,
                ))
    return entries


def _portmis_instances(args: argparse.Namespace) -> list[dict[str, object]]:
    git = collect_git_metadata()
    entries: list[dict[str, object]] = []
    for window_id in args.windows:
        for seed in args.seeds:
            case, metadata = build_portmis_window_case(
                args.calibration_dir,
                window_id=window_id,
                seed=seed,
                forecast_error=args.forecast_error,
                forecast_error_mode=args.forecast_error_mode,
                initial_utilization=args.initial_utilization,
                calibration_scenario_id=args.calibration_scenario_id,
                source_manifest=args.source_manifest,
                require_publication_ready=(
                    args.experiment_phase == "formal"
                    and not args.allow_provisional_source
                ),
            )
            metadata.update({
                "generator_git_commit": git.get("git_commit"),
                "generator_git_branch": git.get("git_branch"),
            })
            entries.append(_archive(
                args.output_dir,
                case=case,
                metadata=metadata,
                overwrite=args.overwrite,
            ))
    return entries


def _pressure_instances(args: argparse.Namespace) -> list[dict[str, object]]:
    git = collect_git_metadata()
    entries: list[dict[str, object]] = []
    for level in args.levels:
        for seed in args.seeds:
            case = build_repair_pressure_case(level=level, seed=seed)
            instance_id = f"pressure_{level}_seed{seed}"
            case.update({
                "instance_id": instance_id,
                "instance_family": "controlled_repair_pressure",
                "instance_protocol": INSTANCE_PROTOCOL,
            })
            metadata = {
                "instance_id": instance_id,
                "instance_family": case["instance_family"],
                "instance_protocol": INSTANCE_PROTOCOL,
                "profile": f"pressure_{level}",
                "pressure_level": level,
                "seed": seed,
                "time_budget_seconds": FORMAL_TIME_BUDGETS_SECONDS[
                    "pressure"
                ],
                "generator_git_commit": git.get("git_commit"),
                "generator_git_branch": git.get("git_branch"),
                "source_publication_ready": None,
            }
            entries.append(_archive(
                args.output_dir,
                case=case,
                metadata=metadata,
                overwrite=args.overwrite,
            ))
    return entries


def _write_index(
    path: Path,
    *,
    args: argparse.Namespace,
    entries: list[dict[str, object]],
) -> None:
    indexed_entries = [
        {
            **entry,
            "instance_bundle_filename": Path(
                str(entry["instance_bundle_path"])
            ).name,
        }
        for entry in entries
    ]
    payload = {
        "index_schema": "rolling-instance-index-v1",
        "instance_protocol": INSTANCE_PROTOCOL,
        "experiment_phase": args.experiment_phase,
        "command": list(sys.argv),
        "entry_count": len(indexed_entries),
        "entries": indexed_entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not args.overwrite:
        raise FileExistsError(
            f"instance index already exists; use a new path: {path}"
        )
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-phase",
        choices=("development", "preflight", "formal"),
        default="development",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("local_results/formal/instances"),
    )
    parser.add_argument("--index-output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    subparsers = parser.add_subparsers(dest="family", required=True)

    synthetic = subparsers.add_parser("synthetic")
    synthetic.add_argument("--sizes", nargs="+", choices=PRESETS, default=["small"])
    synthetic.add_argument("--seeds", nargs="+", type=int, default=[100])
    synthetic.add_argument("--forecast-error", type=float, default=0.10)
    synthetic.add_argument(
        "--forecast-error-mode",
        choices=FORECAST_ERROR_MODES,
        default="multiplicative",
    )
    synthetic.add_argument("--initial-utilization", type=float, default=0.25)
    synthetic.add_argument("--outbound-rate", type=int, default=150)
    synthetic.add_argument("--release-delay-periods", type=int, default=0)
    synthetic.add_argument("--ship-volume-factor", type=float, default=1.0)
    synthetic.add_argument("--certify-oracle", action="store_true")
    synthetic.add_argument(
        "--capacity-pressure-profiles",
        nargs="*",
        choices=tuple(FORMAL_SYNTHETIC_PRESSURE_TARGETS),
        default=[],
    )
    synthetic.add_argument(
        "--oracle-case-classes",
        nargs="*",
        choices=("feasible", "tight", "overloaded"),
        default=[],
    )
    synthetic.add_argument(
        "--oracle-factor-bounds", nargs=2, type=float, default=(0.25, 4.0)
    )
    synthetic.add_argument("--oracle-search-iterations", type=int, default=8)
    synthetic.add_argument("--pressure-search-iterations", type=int, default=14)
    synthetic.add_argument(
        "--pressure-target-tolerance",
        type=float,
        default=FORMAL_SYNTHETIC_PRESSURE_TARGET_TOLERANCE,
    )
    synthetic.add_argument("--oracle-time", type=float, default=60.0)
    synthetic.add_argument("--oracle-threads", type=int, default=1)

    portmis = subparsers.add_parser("portmis")
    portmis.add_argument(
        "--windows",
        nargs="+",
        choices=tuple(FORMAL_PUBLIC_WINDOWS) + tuple(
            FORMAL_PUBLIC_TEMPORAL_WINDOWS
        ),
        default=list(FORMAL_PUBLIC_WINDOWS),
    )
    portmis.add_argument("--seeds", nargs="+", type=int, default=[100])
    portmis.add_argument(
        "--calibration-dir",
        type=Path,
        default=Path(
            "local_results/portmis_pilot_2025_07/calibrated_demand_v1"
        ),
    )
    portmis.add_argument("--source-manifest", type=Path)
    portmis.add_argument("--allow-provisional-source", action="store_true")
    portmis.add_argument("--forecast-error", type=float, default=0.10)
    portmis.add_argument(
        "--forecast-error-mode",
        choices=FORECAST_ERROR_MODES,
        default="multiplicative",
    )
    portmis.add_argument("--initial-utilization", type=float, default=0.25)
    portmis.add_argument(
        "--calibration-scenario-id",
        choices=FORMAL_PUBLIC_CALIBRATION_SCENARIOS,
        default="central",
        help="stable OFAT label such as central, utilization_low, or share40_high",
    )

    pressure = subparsers.add_parser("pressure")
    pressure.add_argument(
        "--levels",
        nargs="+",
        choices=("nearby", "global"),
        default=["nearby", "global"],
    )
    pressure.add_argument("--seeds", nargs="+", type=int, default=[100])

    args = parser.parse_args()
    if args.family == "synthetic" and args.ship_volume_factor <= 0:
        parser.error("--ship-volume-factor must be positive")
    if args.experiment_phase == "formal":
        unexpected = sorted(set(args.seeds) - set(FORMAL_SEEDS))
        if unexpected:
            parser.error(
                f"formal seeds must come from {list(FORMAL_SEEDS)}; "
                f"unexpected={unexpected}"
            )
        git = collect_git_metadata()
        if git.get("git_dirty") is not False:
            parser.error("formal bundle generation requires a clean Git commit")
        if args.overwrite:
            parser.error("formal bundles cannot be overwritten")
        if args.family == "portmis" and args.allow_provisional_source:
            parser.error("formal public bundles cannot allow provisional source")
        if args.family == "synthetic":
            if args.oracle_case_classes and args.capacity_pressure_profiles:
                parser.error(
                    "choose either boundary oracle classes or capacity "
                    "pressure profiles"
                )
            if args.certify_oracle and (
                args.oracle_case_classes or args.capacity_pressure_profiles
            ):
                parser.error(
                    "--certify-oracle is only for fixed-volume utilization "
                    "cases"
                )
            if (
                not args.oracle_case_classes
                and not args.capacity_pressure_profiles
                and not args.certify_oracle
            ):
                parser.error(
                    "formal synthetic bundles require integer oracle "
                    "certification"
                )
            if args.capacity_pressure_profiles:
                if abs(
                    args.initial_utilization
                    - FORMAL_SYNTHETIC_SCALE_INITIAL_UTILIZATION
                ) > 1e-12:
                    parser.error(
                        "formal scale-pressure cases require initial "
                        f"utilization "
                        f"{FORMAL_SYNTHETIC_SCALE_INITIAL_UTILIZATION:g}"
                    )
            elif args.certify_oracle:
                if set(args.sizes) != {
                    FORMAL_SYNTHETIC_UTILIZATION_SIZE
                }:
                    parser.error(
                        "formal utilization-isolation cases require only "
                        f"size {FORMAL_SYNTHETIC_UTILIZATION_SIZE}"
                    )
                if not any(
                    abs(args.initial_utilization - level) <= 1e-12
                    for level in FORMAL_SYNTHETIC_UTILIZATION_LEVELS
                ):
                    parser.error(
                        "formal utilization-isolation level must be one of "
                        f"{FORMAL_SYNTHETIC_UTILIZATION_LEVELS}"
                    )
                if abs(
                    args.ship_volume_factor
                    - FORMAL_SYNTHETIC_UTILIZATION_SHIP_VOLUME_FACTOR
                ) > 1e-12:
                    parser.error(
                        "formal utilization-isolation cases require ship "
                        f"volume factor "
                        f"{FORMAL_SYNTHETIC_UTILIZATION_SHIP_VOLUME_FACTOR:g}"
                    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    builders = {
        "synthetic": _synthetic_instances,
        "portmis": _portmis_instances,
        "pressure": _pressure_instances,
    }
    entries = builders[args.family](args)
    index_output = args.index_output or args.output_dir / (
        f"{args.family}_instance_index.json"
    )
    _write_index(index_output, args=args, entries=entries)
    print(json.dumps({
        "status": "complete",
        "instance_count": len(entries),
        "index": index_output.as_posix(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

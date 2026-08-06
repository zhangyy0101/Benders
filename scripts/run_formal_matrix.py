"""Run frozen instance bundles through one paired publication method matrix."""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    ALGORITHM_VERSION,
    DEPENDENCY_PROFILES,
    FORMAL_PRIMARY_CONFIGURATIONS,
    FORMAL_RESULT_AUTHORIZED,
    FORMAL_SEEDS,
    OPERATION_WEIGHT_PROFILE,
    OPERATION_WEIGHT_PROFILES,
)
from experiment_metadata import (  # noqa: E402
    collect_experiment_metadata,
    write_experiment_artifacts,
)
from external_baselines import (  # noqa: E402
    CONFIGURATIONS,
    DRA_PARAMETER_PROFILES,
)
from formal_experiments import (  # noqa: E402
    INSTANCE_PROTOCOL,
    read_instance_bundle,
    sha256_file,
)
from rolling_experiment import run_rolling_case  # noqa: E402
from run_experiments import (  # noqa: E402
    _resume_rows,
    experiment_identity,
    planned_experiment_identity,
    result_row,
)


EXPERIMENT_SET_CONFIGURATIONS = {
    "main": FORMAL_PRIMARY_CONFIGURATIONS,
    "aggregate_ablation": (
        "full_bottleneck",
        "full_bottleneck_no_aggregate",
    ),
    "internal_ablation": (
        "core",
        "core_start",
        "core_start_impact",
        "full_bottleneck",
    ),
    "public_sensitivity": ("core_start", "full_bottleneck"),
    "public_temporal_robustness": ("core_start", "full_bottleneck"),
    "repair_mechanism": ("full_direct", "full_bottleneck", "full"),
    "dra_sensitivity": ("dra_rpm",),
    "operation_weight_sensitivity": ("core_start", "full_bottleneck"),
}


def _expand_bundle_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        candidate = Path(value)
        if candidate.is_dir():
            paths.extend(sorted(candidate.glob("*.instance.json")))
        elif any(symbol in value for symbol in "*?[]"):
            paths.extend(Path(match) for match in sorted(glob.glob(value)))
        else:
            paths.append(candidate)
    unique = []
    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            unique.append(resolved)
            seen.add(resolved)
    if not unique:
        raise ValueError("no instance bundles selected")
    return unique


def _paths_from_indexes(
    values: list[str],
    *,
    require_formal: bool,
    required_phase: str | None = None,
) -> tuple[list[Path], dict[Path, dict], list[dict]]:
    paths: list[Path] = []
    expected: dict[Path, dict] = {}
    index_records: list[dict] = []
    for value in values:
        index_path = Path(value).resolve()
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if payload.get("index_schema") != "rolling-instance-index-v1":
            raise ValueError(f"unsupported instance index: {index_path}")
        if payload.get("instance_protocol") != INSTANCE_PROTOCOL:
            raise ValueError(f"instance index protocol mismatch: {index_path}")
        if int(payload.get("entry_count", -1)) != len(
            payload.get("entries", [])
        ):
            raise ValueError(f"instance index entry count mismatch: {index_path}")
        phase = "formal" if require_formal else required_phase
        if phase is not None and payload.get("experiment_phase") != phase:
            raise ValueError(
                f"{phase} matrix requires a {phase} instance index: "
                f"{index_path}"
            )
        if (
            require_formal
            and payload.get("formal_results_authorized") is not True
        ):
            raise ValueError(
                "formal matrix requires an explicitly authorized instance index: "
                f"{index_path}"
            )
        index_records.append({
            "path": index_path.as_posix(),
            "sha256": sha256_file(index_path),
            "experiment_phase": payload.get("experiment_phase"),
            "formal_results_authorized": payload.get(
                "formal_results_authorized"
            ),
        })
        for entry in payload["entries"]:
            path = (
                index_path.parent
                / str(entry["instance_bundle_filename"])
            ).resolve()
            if path in expected:
                raise ValueError(f"duplicate bundle across indexes: {path}")
            if not path.is_file():
                raise FileNotFoundError(path)
            actual_file_hash = sha256_file(path)
            if actual_file_hash != entry.get("instance_bundle_sha256"):
                raise ValueError(f"bundle/index SHA-256 mismatch: {path}")
            paths.append(path)
            expected[path] = entry
    if not paths:
        raise ValueError("instance indexes contain no bundles")
    return paths, expected, index_records


def _validate_frozen_preflight_request(
    *,
    experiment_set: str,
    configurations: tuple[str, ...],
    parameter_profiles: tuple[str, ...],
    uses_indexes: bool,
    time_override: float | None,
    threads: int,
    mip_gap: float,
    dependency_profile: str,
    operation_weight_profile: str,
    git_dirty: bool | None,
) -> None:
    """Reject a preflight request that differs from the frozen protocol."""

    if git_dirty is not False:
        raise ValueError("preflight matrix requires a clean Git commit")
    if not uses_indexes:
        raise ValueError("preflight matrix requires --bundle-indexes")
    if time_override is not None:
        raise ValueError(
            "preflight matrix must use frozen per-bundle time budgets"
        )
    if threads != 1:
        raise ValueError("preflight matrix requires exactly one solver thread")
    if abs(float(mip_gap) - .01) > 1e-12:
        raise ValueError("preflight matrix requires the frozen 1% MIP gap")
    if experiment_set != "main":
        return
    if configurations != tuple(FORMAL_PRIMARY_CONFIGURATIONS):
        raise ValueError("preflight main matrix must use the frozen five methods")
    if parameter_profiles != ("frozen",):
        raise ValueError(
            "preflight main matrix must use the frozen DRA-RPM profile"
        )
    if dependency_profile != "current":
        raise ValueError(
            "preflight main matrix must use the current dependency profile"
        )
    if operation_weight_profile != OPERATION_WEIGHT_PROFILE:
        raise ValueError(
            "preflight main matrix must use the frozen business "
            "operation-weight profile"
        )


def _validate_fresh_publication_output(
    *,
    output_csv: str,
    manifest_output: str | None,
    resume: bool,
) -> None:
    """Prevent an initial publication run from overwriting any checkpoint."""

    if resume:
        return
    output_path = Path(output_csv)
    manifest_path = (
        Path(manifest_output)
        if manifest_output is not None
        else output_path.with_suffix(".manifest.json")
    )
    if output_path.exists() or manifest_path.exists():
        raise ValueError(
            "publication output already exists; choose a new output root or "
            "use --resume with the identical frozen request"
        )


def _method_profiles(
    configurations: tuple[str, ...],
    parameter_profiles: tuple[str, ...],
) -> list[tuple[str, str]]:
    return [
        (configuration, profile)
        for configuration in configurations
        for profile in (
            parameter_profiles if configuration == "dra_rpm" else ("frozen",)
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundles", nargs="+")
    parser.add_argument("--bundle-indexes", nargs="+")
    parser.add_argument(
        "--experiment-set",
        choices=tuple(EXPERIMENT_SET_CONFIGURATIONS) + ("custom",),
        default="main",
    )
    parser.add_argument("--configurations", nargs="+", choices=CONFIGURATIONS)
    parser.add_argument(
        "--baseline-parameter-profiles",
        nargs="+",
        choices=DRA_PARAMETER_PROFILES,
    )
    parser.add_argument(
        "--experiment-phase",
        choices=("development", "preflight", "formal"),
        default="development",
    )
    parser.add_argument("--time", type=float)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--mip-gap", type=float, default=0.01)
    parser.add_argument(
        "--dependency-profile",
        choices=DEPENDENCY_PROFILES,
        default="current",
    )
    parser.add_argument(
        "--operation-weight-profile",
        choices=tuple(OPERATION_WEIGHT_PROFILES),
        default=OPERATION_WEIGHT_PROFILE,
    )
    parser.add_argument(
        "--output",
        default="local_results/formal/runs/formal_results.csv",
    )
    parser.add_argument("--manifest-output")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if bool(args.bundles) == bool(args.bundle_indexes):
        parser.error("select exactly one of --bundles or --bundle-indexes")

    if args.experiment_set == "custom" and not args.configurations:
        parser.error("custom experiment set requires --configurations")
    configurations = tuple(
        args.configurations
        or EXPERIMENT_SET_CONFIGURATIONS[args.experiment_set]
    )
    parameter_profiles = tuple(
        args.baseline_parameter_profiles
        or (
            tuple(DRA_PARAMETER_PROFILES)
            if args.experiment_set == "dra_sensitivity"
            else ("frozen",)
        )
    )
    method_profiles = _method_profiles(configurations, parameter_profiles)
    if args.bundle_indexes:
        bundle_paths, expected_bundles, index_records = _paths_from_indexes(
            args.bundle_indexes,
            require_formal=args.experiment_phase == "formal",
            required_phase=(
                args.experiment_phase
                if args.experiment_phase in {"preflight", "formal"}
                else None
            ),
        )
    else:
        bundle_paths = _expand_bundle_paths(args.bundles)
        expected_bundles = {}
        index_records = []
    bundles = []
    for path in bundle_paths:
        case, instance_metadata = read_instance_bundle(path)
        expected = expected_bundles.get(path)
        if expected is not None:
            if (
                instance_metadata["instance_bundle_sha256"]
                != expected.get("instance_bundle_sha256")
                or instance_metadata["instance_case_sha256"]
                != expected.get("instance_case_sha256")
                or instance_metadata.get("instance_id")
                != expected.get("instance_id")
            ):
                raise ValueError(f"bundle identity differs from index: {path}")
        seed = int(instance_metadata["seed"])
        budget = (
            float(args.time)
            if args.time is not None
            else float(instance_metadata["time_budget_seconds"])
        )
        bundles.append((case, instance_metadata, seed, budget))

    max_budget = max(item[3] for item in bundles)
    metadata = collect_experiment_metadata(
        threads=args.threads,
        mip_gap=args.mip_gap,
        time_limit=max_budget,
        dependency_profile=args.dependency_profile,
        operation_weight_profile=args.operation_weight_profile,
        experiment_phase=args.experiment_phase,
    )
    metadata.update({
        "experiment_set": args.experiment_set,
        "time_budget_policy": (
            "command_override" if args.time is not None
            else "frozen_per_instance_bundle"
        ),
    })
    if args.experiment_phase == "preflight":
        try:
            _validate_frozen_preflight_request(
                experiment_set=args.experiment_set,
                configurations=configurations,
                parameter_profiles=parameter_profiles,
                uses_indexes=bool(args.bundle_indexes),
                time_override=args.time,
                threads=args.threads,
                mip_gap=args.mip_gap,
                dependency_profile=args.dependency_profile,
                operation_weight_profile=args.operation_weight_profile,
                git_dirty=metadata.get("git_dirty"),
            )
        except ValueError as exc:
            parser.error(str(exc))
    if args.experiment_phase == "formal":
        if not FORMAL_RESULT_AUTHORIZED:
            parser.error(
                "formal execution is not authorized for algorithm "
                f"{ALGORITHM_VERSION}; register a new untouched confirmatory "
                "set first"
            )
        unexpected = sorted(
            {item[2] for item in bundles} - set(FORMAL_SEEDS)
        )
        if unexpected:
            parser.error(
                f"formal bundle seeds must come from {list(FORMAL_SEEDS)}; "
                f"unexpected={unexpected}"
            )
        if metadata.get("git_dirty") is not False:
            parser.error("formal matrix requires a clean Git commit")
        if not args.bundle_indexes:
            parser.error("formal matrix requires --bundle-indexes")
        if args.time is not None:
            parser.error("formal matrix must use frozen per-bundle time budgets")
        provisional = [
            item[1]["instance_id"]
            for item in bundles
            if item[1].get("instance_family")
            == "public_data_calibrated_semi_synthetic"
            and item[1].get("source_publication_ready") is not True
        ]
        if provisional:
            parser.error(
                "formal public-data bundles are provisional: "
                + ", ".join(provisional)
            )
        noncentral = [
            item[1]["instance_id"]
            for item in bundles
            if item[1].get("instance_family")
            == "public_data_calibrated_semi_synthetic"
            and item[1].get("calibration_scenario_id") != "central"
        ]
        if args.experiment_set in {"main", "dra_sensitivity"} and noncentral:
            parser.error(
                f"{args.experiment_set} requires central public calibration: "
                + ", ".join(noncentral)
            )
        temporal_public = [
            item[1]["instance_id"]
            for item in bundles
            if item[1].get("public_panel_role") == "temporal_robustness"
        ]
        if args.experiment_set == "main" and temporal_public:
            parser.error(
                "formal main matrix cannot pool the public temporal panel: "
                + ", ".join(temporal_public)
            )
        if args.experiment_set == "public_temporal_robustness":
            wrong_panel = [
                item[1]["instance_id"]
                for item in bundles
                if item[1].get("public_panel_role") != "temporal_robustness"
            ]
            if wrong_panel:
                parser.error(
                    "public temporal robustness requires only temporal-panel "
                    "bundles: " + ", ".join(wrong_panel)
                )
        if args.experiment_set == "main":
            if configurations != tuple(FORMAL_PRIMARY_CONFIGURATIONS):
                parser.error(
                    "formal main matrix must use the frozen five methods"
                )
            if parameter_profiles != ("frozen",):
                parser.error(
                    "formal main matrix must use the frozen DRA-RPM profile"
                )
            if args.operation_weight_profile != OPERATION_WEIGHT_PROFILE:
                parser.error(
                    "formal main matrix must use the frozen business "
                    "operation-weight profile"
                )

    if args.experiment_phase in {"preflight", "formal"}:
        try:
            _validate_fresh_publication_output(
                output_csv=args.output,
                manifest_output=args.manifest_output,
                resume=args.resume,
            )
        except ValueError as exc:
            parser.error(str(exc))

    requested_matrix = {
        "experiment_set": args.experiment_set,
        "experiment_phase": args.experiment_phase,
        "instance_bundles": [
            {
                "path": item[1]["instance_bundle_path"],
                "sha256": item[1]["instance_bundle_sha256"],
                "case_sha256": item[1]["instance_case_sha256"],
                "instance_id": item[1]["instance_id"],
                "seed": item[2],
                "time_budget_seconds": item[3],
            }
            for item in bundles
        ],
        "instance_indexes": index_records,
        "configurations": list(configurations),
        "baseline_parameter_profiles": list(parameter_profiles),
        "threads": args.threads,
        "mip_gap": args.mip_gap,
        "dependency_profile": args.dependency_profile,
        "operation_weight_profile": args.operation_weight_profile,
        "time_budget_policy": metadata["time_budget_policy"],
    }
    expected_row_count = len(bundles) * len(method_profiles)
    rows = (
        _resume_rows(
            output_csv=args.output,
            manifest_output=args.manifest_output,
            metadata=metadata,
            requested_matrix=requested_matrix,
        )
        if args.resume else []
    )
    completed = {experiment_identity(row) for row in rows}

    def checkpoint(row: dict) -> None:
        identity = experiment_identity(row)
        if identity in completed:
            raise ValueError(f"duplicate experiment row: {identity}")
        rows.append(row)
        completed.add(identity)
        write_experiment_artifacts(
            rows=rows,
            output_csv=args.output,
            metadata=metadata,
            requested_matrix=requested_matrix,
            manifest_output=args.manifest_output,
            command=list(sys.argv),
            expected_row_count=expected_row_count,
        )
        print(row, flush=True)

    for case, instance_metadata, seed, budget in bundles:
        instance = str(instance_metadata["instance_id"])
        for configuration, parameter_profile in method_profiles:
            identity = planned_experiment_identity(
                instance,
                case,
                configuration,
                seed,
                budget,
                baseline_parameter_profile=parameter_profile,
                operation_weight_profile=args.operation_weight_profile,
                instance_metadata=instance_metadata,
            )
            if identity in completed:
                print(f"resume: skipping {identity}", flush=True)
                continue
            result = run_rolling_case(
                case,
                time_per_cycle=budget,
                mip_gap=args.mip_gap,
                threads=args.threads,
                seed=seed,
                configuration=configuration,
                dependency_profile=args.dependency_profile,
                baseline_parameter_profile=parameter_profile,
                operation_weight_profile=args.operation_weight_profile,
            )
            checkpoint(result_row(
                instance,
                case,
                configuration,
                seed,
                budget,
                result,
                metadata,
                baseline_parameter_profile=parameter_profile,
                instance_metadata=instance_metadata,
            ))
    return 0 if all(
        str(row.get("ok")).lower() == "true" for row in rows
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())

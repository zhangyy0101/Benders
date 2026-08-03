"""Run a frozen formal matrix in balanced, independently checkpointed shards."""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    DEPENDENCY_PROFILES,
    FORMAL_ORCHESTRATION_PROTOCOL,
    FORMAL_PRIMARY_CONFIGURATIONS,
    FORMAL_RESULT_AUTHORIZED,
    OPERATION_WEIGHT_PROFILE,
    OPERATION_WEIGHT_PROFILES,
)
from experiment_metadata import (  # noqa: E402
    collect_experiment_metadata,
    write_experiment_artifacts,
)
from formal_experiments import read_instance_bundle, sha256_file  # noqa: E402
from run_experiments import (  # noqa: E402
    experiment_identity,
    planned_experiment_identity,
)
from scripts.run_formal_matrix import _paths_from_indexes  # noqa: E402


def partition_instance_entries(
    entries: list[dict],
    worker_count: int,
) -> list[list[dict]]:
    """Greedily balance frozen instances by their declared cycle budgets."""

    if worker_count < 1:
        raise ValueError("worker_count must be positive")
    if worker_count > len(entries):
        raise ValueError("worker_count cannot exceed the instance count")
    shards: list[list[tuple[int, dict]]] = [[] for _ in range(worker_count)]
    loads = [0.0] * worker_count
    ranked = sorted(
        enumerate(entries),
        key=lambda item: (
            -float(item[1]["time_budget_seconds"]),
            item[0],
        ),
    )
    for original_position, entry in ranked:
        worker = min(
            range(worker_count),
            key=lambda index: (
                loads[index],
                len(shards[index]),
                index,
            ),
        )
        shards[worker].append((original_position, entry))
        loads[worker] += float(entry["time_budget_seconds"])
    return [
        [entry for _position, entry in sorted(shard)]
        for shard in shards
    ]


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def write_shard_indexes(
    source_index: Path,
    shard_directory: Path,
    worker_count: int,
) -> list[Path]:
    """Write deterministic child indexes whose bundle hashes remain unchanged."""

    payload = json.loads(source_index.read_text(encoding="utf-8"))
    if payload.get("index_schema") != "rolling-instance-index-v1":
        raise ValueError(f"unsupported instance index: {source_index}")
    entries = payload.get("entries", [])
    if int(payload.get("entry_count", -1)) != len(entries):
        raise ValueError("source instance index entry count mismatch")
    partitions = partition_instance_entries(entries, worker_count)
    paths = []
    for worker, partition in enumerate(partitions):
        rewritten = []
        for entry in partition:
            child = dict(entry)
            bundle_path = (
                source_index.parent
                / str(entry["instance_bundle_filename"])
            ).resolve()
            child["instance_bundle_filename"] = Path(
                os.path.relpath(bundle_path, shard_directory)
            ).as_posix()
            rewritten.append(child)
        shard_payload = {
            **payload,
            "command": [
                "scripts/run_formal_sharded_matrix.py",
                "--workers",
                str(worker_count),
            ],
            "entry_count": len(rewritten),
            "entries": rewritten,
            "parent_instance_index": source_index.as_posix(),
            "parent_instance_index_sha256": sha256_file(source_index),
            "formal_orchestration_protocol": FORMAL_ORCHESTRATION_PROTOCOL,
            "parallel_worker_count": worker_count,
            "parallel_shard_index": worker,
        }
        path = shard_directory / (
            f"instance_index.shard-{worker + 1:02d}-of-{worker_count:02d}.json"
        )
        _atomic_json(path, shard_payload)
        paths.append(path)
    return paths


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _formal_context(
    source_index: Path,
    *,
    workers: int,
    threads: int,
    mip_gap: float,
    dependency_profile: str,
    operation_weight_profile: str,
) -> tuple[dict, dict, dict[tuple[str, ...], tuple[int, int]], int]:
    paths, _expected, index_records = _paths_from_indexes(
        [str(source_index)],
        require_formal=True,
    )
    bundles = []
    identity_order: dict[tuple[str, ...], tuple[int, int]] = {}
    for instance_position, path in enumerate(paths):
        case, instance_metadata = read_instance_bundle(path)
        seed = int(instance_metadata["seed"])
        budget = float(instance_metadata["time_budget_seconds"])
        bundles.append((case, instance_metadata, seed, budget))
        for method_position, configuration in enumerate(
            FORMAL_PRIMARY_CONFIGURATIONS
        ):
            identity = planned_experiment_identity(
                str(instance_metadata["instance_id"]),
                case,
                configuration,
                seed,
                budget,
                baseline_parameter_profile="frozen",
                operation_weight_profile=operation_weight_profile,
                instance_metadata=instance_metadata,
            )
            if identity in identity_order:
                raise ValueError(f"duplicate planned identity: {identity}")
            identity_order[identity] = (instance_position, method_position)

    metadata = collect_experiment_metadata(
        threads=threads,
        mip_gap=mip_gap,
        time_limit=max(item[3] for item in bundles),
        dependency_profile=dependency_profile,
        operation_weight_profile=operation_weight_profile,
        experiment_phase="formal",
    )
    metadata.update({
        "experiment_set": "main",
        "time_budget_policy": "frozen_per_instance_bundle",
        "execution_orchestration": {
            "protocol": FORMAL_ORCHESTRATION_PROTOCOL,
            "mode": "balanced_instance_shards",
            "parallel_worker_count": workers,
            "solver_threads_per_worker": threads,
            "worker_outputs": "independent_atomic_csv_and_manifest",
            "merge_guard": "exact_planned_identity_partition",
        },
    })
    requested_matrix = {
        "experiment_set": "main",
        "experiment_phase": "formal",
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
        "configurations": list(FORMAL_PRIMARY_CONFIGURATIONS),
        "baseline_parameter_profiles": ["frozen"],
        "operation_weight_profile": operation_weight_profile,
        "threads": threads,
        "mip_gap": mip_gap,
        "dependency_profile": dependency_profile,
        "time_budget_policy": "frozen_per_instance_bundle",
        "execution_orchestration": metadata["execution_orchestration"],
    }
    return metadata, requested_matrix, identity_order, len(identity_order)


def merge_shard_checkpoints(
    shard_outputs: list[Path],
    *,
    identity_order: dict[tuple[str, ...], tuple[int, int]],
    worker_count: int,
) -> list[dict]:
    """Reject duplicates/extras and return all available rows in formal order."""

    merged: dict[tuple[str, ...], dict] = {}
    for worker, output in enumerate(shard_outputs):
        for row in _read_rows(output):
            identity = experiment_identity(row)
            if identity not in identity_order:
                raise ValueError(f"unexpected shard row identity: {identity}")
            if identity in merged:
                raise ValueError(f"duplicate shard row identity: {identity}")
            row["formal_orchestration_protocol"] = (
                FORMAL_ORCHESTRATION_PROTOCOL
            )
            row["parallel_worker_count"] = worker_count
            row["parallel_shard_index"] = worker
            merged[identity] = row
    return [
        merged[identity]
        for identity in sorted(merged, key=identity_order.__getitem__)
    ]


def validate_worker_artifacts(
    shard_outputs: list[Path],
    shard_indexes: list[Path],
) -> list[dict]:
    """Require complete child manifests and return their immutable hashes."""

    records = []
    methods_per_instance = len(FORMAL_PRIMARY_CONFIGURATIONS)
    for worker, (output, index_path) in enumerate(
        zip(shard_outputs, shard_indexes)
    ):
        manifest_path = output.with_suffix(".manifest.json")
        if not output.exists() or not manifest_path.exists():
            raise RuntimeError(f"missing worker artifacts for shard {worker}")
        rows = _read_rows(output)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        index = json.loads(index_path.read_text(encoding="utf-8"))
        expected = int(index["entry_count"]) * methods_per_instance
        if int(manifest.get("row_count", -1)) != len(rows):
            raise RuntimeError(f"worker {worker} CSV/manifest row mismatch")
        if int(manifest.get("expected_row_count", -1)) != expected:
            raise RuntimeError(f"worker {worker} expected-row mismatch")
        if len(rows) != expected or manifest.get("complete") is not True:
            raise RuntimeError(f"worker {worker} checkpoint is incomplete")
        if (
            manifest.get("metadata", {}).get("formal_orchestration_protocol")
            != FORMAL_ORCHESTRATION_PROTOCOL
        ):
            raise RuntimeError(f"worker {worker} orchestration mismatch")
        records.append({
            "parallel_shard_index": worker,
            "row_count": len(rows),
            "all_ok": manifest.get("all_ok"),
            "instance_index_sha256": sha256_file(index_path),
            "output_csv_sha256": sha256_file(output),
            "manifest_sha256": sha256_file(manifest_path),
        })
    return records


def _validate_fresh_paths(
    final_output: Path,
    shard_directory: Path,
    *,
    resume: bool,
) -> None:
    existing = [
        path
        for path in (
            final_output,
            final_output.with_suffix(".manifest.json"),
            shard_directory,
        )
        if path.exists()
    ]
    if existing and not resume:
        raise ValueError(
            "fresh sharded run requires absent outputs; existing="
            + ", ".join(str(path) for path in existing)
        )
    if resume and not shard_directory.exists():
        raise ValueError("resume requires the existing shard directory")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-index", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--mip-gap", type=float, default=.01)
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
        default="local_results/formal/runs/public_main.csv",
    )
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 2:
        parser.error("sharded execution requires at least two workers")
    if args.threads < 1:
        parser.error("threads must be positive")
    if not FORMAL_RESULT_AUTHORIZED:
        parser.error(
            "formal execution is not authorized for objective version 1.5.0; "
            "register a new untouched confirmatory set first"
        )

    source_index = Path(args.bundle_index).resolve()
    final_output = Path(args.output).resolve()
    shard_directory = final_output.with_suffix(".shards")
    _validate_fresh_paths(
        final_output,
        shard_directory,
        resume=args.resume,
    )
    if not args.resume:
        shard_directory.mkdir(parents=True)
    shard_indexes = write_shard_indexes(
        source_index,
        shard_directory,
        args.workers,
    )
    shard_outputs = [
        shard_directory / f"worker-{worker + 1:02d}.csv"
        for worker in range(args.workers)
    ]
    metadata, requested_matrix, identity_order, expected_rows = (
        _formal_context(
            source_index,
            workers=args.workers,
            threads=args.threads,
            mip_gap=args.mip_gap,
            dependency_profile=args.dependency_profile,
            operation_weight_profile=args.operation_weight_profile,
        )
    )
    if metadata.get("git_dirty") is not False:
        parser.error("formal sharded matrix requires a clean Git commit")

    processes = []
    log_streams = []
    for worker, (index_path, output_path) in enumerate(
        zip(shard_indexes, shard_outputs)
    ):
        stdout_path = shard_directory / f"worker-{worker + 1:02d}.stdout.log"
        stderr_path = shard_directory / f"worker-{worker + 1:02d}.stderr.log"
        stdout = stdout_path.open("a" if args.resume else "w", encoding="utf-8")
        stderr = stderr_path.open("a" if args.resume else "w", encoding="utf-8")
        log_streams.extend((stdout, stderr))
        command = [
            sys.executable,
            str(ROOT / "scripts" / "run_formal_matrix.py"),
            "--bundle-indexes",
            str(index_path),
            "--experiment-set",
            "main",
            "--experiment-phase",
            "formal",
            "--threads",
            str(args.threads),
            "--mip-gap",
            str(args.mip_gap),
            "--dependency-profile",
            args.dependency_profile,
            "--operation-weight-profile",
            args.operation_weight_profile,
            "--output",
            str(output_path),
        ]
        if args.resume:
            command.append("--resume")
        processes.append(subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
        ))

    last_count = -1
    try:
        while any(process.poll() is None for process in processes):
            rows = merge_shard_checkpoints(
                shard_outputs,
                identity_order=identity_order,
                worker_count=args.workers,
            )
            if rows and len(rows) != last_count:
                write_experiment_artifacts(
                    rows=rows,
                    output_csv=final_output,
                    metadata=metadata,
                    requested_matrix=requested_matrix,
                    command=list(sys.argv),
                    expected_row_count=expected_rows,
                )
                last_count = len(rows)
                print(
                    f"parallel checkpoint: {last_count}/{expected_rows}",
                    flush=True,
                )
            time.sleep(max(.2, args.poll_seconds))
    except BaseException:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        raise
    finally:
        for stream in log_streams:
            stream.close()

    rows = merge_shard_checkpoints(
        shard_outputs,
        identity_order=identity_order,
        worker_count=args.workers,
    )
    if rows:
        write_experiment_artifacts(
            rows=rows,
            output_csv=final_output,
            metadata=metadata,
            requested_matrix=requested_matrix,
            command=list(sys.argv),
            expected_row_count=expected_rows,
        )
    return_codes = [process.returncode for process in processes]
    if any(code not in (0, 2) for code in return_codes):
        raise RuntimeError(f"shard worker failures: {return_codes}")
    metadata["completed_shard_artifacts"] = validate_worker_artifacts(
        shard_outputs,
        shard_indexes,
    )
    if len(rows) != expected_rows:
        raise RuntimeError(
            f"incomplete sharded matrix: {len(rows)}/{expected_rows}"
        )
    write_experiment_artifacts(
        rows=rows,
        output_csv=final_output,
        metadata=metadata,
        requested_matrix=requested_matrix,
        command=list(sys.argv),
        expected_row_count=expected_rows,
    )
    return 0 if all(
        str(row.get("ok")).strip().lower() == "true"
        for row in rows
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())

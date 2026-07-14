"""Supported, resumable entry point for candidate algorithm experiments."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configurations import get_algorithm_configuration, list_algorithm_configurations
from benchmark_io import instance_digest, load_instance
from experiment_runner import run_jobs


def parser(*, include_historical=False):
    value = argparse.ArgumentParser(description="Run registered BBC candidate configurations")
    value.add_argument("--suite-dir", default="benchmarks/paper_exp_v1_pilot21")
    value.add_argument("--instances", nargs="+")
    value.add_argument("--budget", type=float, default=300)
    value.add_argument("--seeds", nargs="+", type=int, default=[0])
    value.add_argument("--threads", type=int, default=1)
    value.add_argument("--mip-gap", type=float, default=.03)
    value.add_argument("--output", default="experiments/candidate_runs")
    value.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    value.add_argument("--rerun-failed", action="store_true")
    value.add_argument("--save-solutions", action="store_true")
    value.add_argument("--include-historical-configs", action="store_true",
                       help="show and allow archived development configurations")
    value.add_argument("--algorithm-config",
                       choices=list_algorithm_configurations(include_historical=include_historical),
                       default="algorithm-candidate-v1")
    value.add_argument("--require-clean-git", action="store_true")
    return value


def build_jobs(args):
    root = Path(args.suite_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    wanted = set(args.instances or [row["instance_id"] for row in manifest["instances"]])
    entries = [row for row in manifest["instances"] if row["instance_id"] in wanted]
    missing = wanted - {row["instance_id"] for row in entries}
    if missing:
        raise ValueError(f"unknown suite instances: {sorted(missing)}")
    configuration = get_algorithm_configuration(args.algorithm_config)
    jobs = []
    for row in entries:
        path = root / row["relative_path"]
        digest = instance_digest(load_instance(path))
        if digest != row["digest"]:
            raise ValueError(f"fatal digest mismatch for {row['instance_id']}")
        for seed in args.seeds:
            jobs.append({"instance_id": row["instance_id"], "instance_path": path, "expected_digest": digest,
                         "method": "bbc_candidate", "configuration": configuration, "seed": seed,
                         "budget": args.budget, "threads": args.threads, "mip_gap": args.mip_gap,
                         "alloc_domain": "integer", "handling_rate_scale": 1.0, "outbound_policy": "proportional"})
    return jobs


def main():
    include_historical = "--include-historical-configs" in sys.argv[1:]
    args = parser(include_historical=include_historical).parse_args()
    jobs = build_jobs(args)
    rows = run_jobs(jobs, args.output, resume=args.resume, rerun_failed=args.rerun_failed,
                    save_solutions=args.save_solutions, command=" ".join(sys.argv),
                    require_clean_git=args.require_clean_git)
    print(f"results: {len(rows)} total rows, {len(jobs)} requested candidate jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

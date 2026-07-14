"""Run the phase-01 Aggregate Guide smoke gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import load_instance
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from solver_aggregate_guide import solve_aggregate_guide


DEFAULT_LIMITS = {"tiny": 0.5, "XS01": 0.5, "S01": 0.75, "M01": 2.0, "L01": 5.0}
OUTPUT = Path("validation/aggregate_guide_smoke")


def _raw_instance(instance_id):
    if instance_id == "tiny":
        return build_builtin_instance("tiny")
    if instance_id == "XS01":
        return load_instance("benchmarks/paper_exp_v1_pilot21_exact/XS01.json")
    size = {"S01": "small", "M01": "medium", "L01": "large"}[instance_id]
    return load_instance(f"benchmarks/paper_exp_v1_pilot21/{size}/{instance_id}.json")


def _jsonable_map(values):
    return [{"key": list(key), "value": value} for key, value in values.items()]


def _jsonable(result):
    payload = {key: value for key, value in result.items() if key not in {"x", "alloc_boxes", "aggregate_z", "diagnostics"}}
    payload["support_counts"] = {
        "x": len(result["x"]), "alloc_boxes": len(result["alloc_boxes"]), "aggregate_z": len(result["aggregate_z"])
    }
    diagnostics = dict(result["diagnostics"])
    for key in ("aggregate_flow_by_ship_size_block", "alloc_support_by_ship_group_bay", "x_support_by_ship_bay"):
        diagnostics[key] = _jsonable_map(diagnostics[key])
    payload["diagnostics"] = diagnostics
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", nargs="+", choices=tuple(DEFAULT_LIMITS), default=tuple(DEFAULT_LIMITS))
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for instance_id in args.instances:
        try:
            result = solve_aggregate_guide(
                prepare_instance(_raw_instance(instance_id)), Weights(), time_limit=DEFAULT_LIMITS[instance_id],
                threads=args.threads, seed=args.seed,
            )
            row = {"instance_id": instance_id, "time_limit": DEFAULT_LIMITS[instance_id], **_jsonable(result), "exception": None}
        except Exception as exc:
            row = {"instance_id": instance_id, "time_limit": DEFAULT_LIMITS[instance_id], "ok": False,
                   "source": None, "exception": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(f"{instance_id}: {row.get('source')} ({row.get('status_name')})", flush=True)
    config = get_algorithm_configuration("algorithm-candidate-v1")
    required = set(("positive_x_count", "positive_alloc_count", "positive_z_count", "fractional_x_count",
                    "fractional_alloc_count", "aggregate_flow_by_ship_size_block",
                    "alloc_support_by_ship_group_bay", "x_support_by_ship_bay"))
    passed = (
        all(row.get("ok") and row.get("source") in {"mip_incumbent", "lp_fallback", "static_fallback"}
            and required <= set(row.get("diagnostics", {})) and row.get("exception") is None for row in rows)
        and config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH
    )
    report = {"status": "PASS" if passed else "FAIL", "stage": "01_aggregate_guide",
              "candidate_hash": config["configuration_hash"], "candidate_hash_unchanged": config["configuration_hash"] == FROZEN_CANDIDATE_V1_HASH,
              "exceptions": sum(row.get("exception") is not None for row in rows), "instances": rows}
    (args.output / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = "\n".join(
        f"- {row['instance_id']}: `{row.get('source')}`, status `{row.get('status_name')}`, runtime {row.get('runtime', 0):.3f}s"
        for row in rows
    )
    (args.output / "report.md").write_text(
        f"# Aggregate Guide smoke\n\nStatus: **{report['status']}**\n\n{summary}\n\n"
        f"Candidate-v1 hash unchanged: {report['candidate_hash_unchanged']}\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

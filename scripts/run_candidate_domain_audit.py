"""Audit Stage-02 candidate domains without constructing a repair model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import load_instance
from candidate_domain import build_candidate_domain
from config import Weights
from data import prepare_instance
from instance_registry import build_builtin_instance
from model_common import ship_groups
from solver_aggregate_guide import solve_aggregate_guide


INSTANCES = ("tiny", "XS01", "XS02", "XS03", "S01", "M01", "L01")
LIMITS = {"tiny": .5, "XS01": .5, "XS02": .5, "XS03": .5, "S01": .75, "M01": 2.0, "L01": 5.0}
OUTPUT = Path("validation/candidate_domain_audit")


def raw_instance(instance_id):
    if instance_id == "tiny":
        return build_builtin_instance("tiny")
    if instance_id.startswith("XS"):
        return load_instance(f"benchmarks/paper_exp_v1_pilot21_exact/{instance_id}.json")
    size = {"S01": "small", "M01": "medium", "L01": "large"}[instance_id]
    return load_instance(f"benchmarks/paper_exp_v1_pilot21/{size}/{instance_id}.json")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for instance_id in INSTANCES:
        try:
            data = prepare_instance(raw_instance(instance_id))
            guide = solve_aggregate_guide(data, Weights(), time_limit=LIMITS[instance_id], threads=1, seed=0)
            domain = build_candidate_domain(data, guide)
            repeated = build_candidate_domain(data, guide)
            diagnostics = domain["diagnostics"]
            zero_groups = [f"{j}|{g}" for j in data["J_new"] for g in ship_groups(data, j) if not domain["candidate_bays"][j, g]]
            deterministic = (domain["candidate_blocks"] == repeated["candidate_blocks"] and
                             domain["candidate_bays"] == repeated["candidate_bays"] and
                             domain["candidate_ship_bays"] == repeated["candidate_ship_bays"])
            row = {"instance_id": instance_id, "guide_source": guide["source"], "guide_status": guide["status_name"],
                   "zero_candidate_groups": zero_groups, "deterministic": deterministic,
                   "individual_coverage_pass": diagnostics["individual_coverage_pass"],
                   "joint_coverage_status": diagnostics["joint_coverage_status"],
                   "candidate_group_bay_pair_count": diagnostics["candidate_group_bay_pair_count"],
                   "full_group_bay_pair_count": diagnostics["full_group_bay_pair_count"],
                   "candidate_pair_ratio": diagnostics["candidate_pair_ratio"],
                   "candidate_ship_bay_pair_count": diagnostics["candidate_ship_bay_pair_count"],
                   "forced_soft_cap_exception_count": len(diagnostics["forced_soft_cap_exceptions"]),
                   "joint_expansion_rounds": diagnostics["joint_expansion_rounds"], "exception": None}
        except Exception as exc:
            row = {"instance_id": instance_id, "exception": f"{type(exc).__name__}: {exc}"}
        rows.append(row)
        print(f"{instance_id}: {row.get('joint_coverage_status')} ratio={row.get('candidate_pair_ratio')}", flush=True)
    candidate_hash = get_algorithm_configuration("algorithm-candidate-v1")["configuration_hash"]
    passed = all(not row.get("exception") and not row["zero_candidate_groups"] and row["individual_coverage_pass"]
                 and row["joint_coverage_status"] != "infeasible" and row["deterministic"] for row in rows)
    passed = passed and candidate_hash == FROZEN_CANDIDATE_V1_HASH
    report = {"status": "PASS" if passed else "FAIL", "stage": "02_candidate_domain",
              "candidate_hash": candidate_hash, "candidate_hash_unchanged": candidate_hash == FROZEN_CANDIDATE_V1_HASH,
              "instances": rows}
    (OUTPUT / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [f"- {r['instance_id']}: joint `{r.get('joint_coverage_status')}`, ratio {r.get('candidate_pair_ratio', 0):.3f}, deterministic {r.get('deterministic')}" for r in rows]
    (OUTPUT / "report.md").write_text(f"# Candidate domain audit\n\nStatus: **{report['status']}**\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

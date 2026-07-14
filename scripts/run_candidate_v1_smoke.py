"""Short, resumable P5 smoke gate for immutable algorithm-candidate-v1."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configuration import FROZEN_CANDIDATE_V1_HASH
from algorithm_configurations import get_algorithm_configuration
from benchmark_io import instance_digest, load_instance
from experiment_runner import run_jobs

OUTPUT = Path("validation/candidate_v1_smoke")
MATH_FIELDS = ("root_prepass", "warm_start", "alns", "aggregate_recourse_lb",
               "analytic_recourse_lb", "valid_inequalities", "node_cuts", "cut_strategy", "phase_shares")


def manifest_row(root, instance_id):
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return next(row for row in manifest["instances"] if row["instance_id"] == instance_id)


def job(root, instance_id, configuration, budget):
    row = manifest_row(root, instance_id); path = root / row["relative_path"]
    digest = instance_digest(load_instance(path))
    if digest != row["digest"]:
        raise ValueError(f"fatal digest mismatch for {instance_id}")
    return {"instance_id": instance_id, "instance_path": path, "expected_digest": digest,
            "method": "bbc_candidate", "configuration": configuration, "seed": 0,
            "budget": budget, "threads": 1, "mip_gap": 0.0 if instance_id == "XS01" else .03,
            "alloc_domain": "integer", "handling_rate_scale": 1.0, "outbound_policy": "proportional"}


def check_candidate(row):
    identity, config = row["identity"], row["configuration"]
    errors = []
    if identity["configuration_name"] != "algorithm-candidate-v1": errors.append("configuration name")
    if identity["configuration_hash"] != FROZEN_CANDIDATE_V1_HASH: errors.append("configuration hash")
    if "alns" in identity["resolved_algorithm_label"].lower(): errors.append("ALNS display label")
    if config["analytic_recourse_lb"] or config["valid_inequalities"]: errors.append("disabled strengthening")
    if not config["aggregate_recourse_lb"]: errors.append("size aggregate LB")
    diagnostics = row.get("method_diagnostics") or {}
    if (diagnostics.get("root") or {}).get("runtime") not in (None, 0, 0.0): errors.append("root runtime")
    if (diagnostics.get("warm") or {}).get("enabled") not in (None, False): errors.append("warm enabled")
    if (diagnostics.get("alns") or {}).get("enabled") not in (None, False): errors.append("ALNS enabled")
    if not row["status"]["feasible_incumbent_found"] or not row["evaluation"]["feasibility"]["feasible"]: errors.append("solution checker")
    ub, lb = row["optimization"]["ub"], row["optimization"]["lb"]
    if ub is None or lb is None or lb > ub + 1e-6: errors.append("LB <= UB")
    trace = row.get("anytime_trace", [])
    if not trace or trace[-1].get("phase") != "final" or trace[-1].get("ub") is None: errors.append("final trace")
    return errors


def main():
    candidate = get_algorithm_configuration("algorithm-candidate-v1")
    c2 = get_algorithm_configuration("C2_core_aggregate")
    exact_root = Path("benchmarks/paper_exp_v1_pilot21_exact")
    suite_root = Path("benchmarks/paper_exp_v1_pilot21")
    jobs = [job(exact_root, "XS01", candidate, 20), job(exact_root, "XS01", c2, 20),
            job(suite_root, "S01", candidate, 30)]
    rows = run_jobs(jobs, OUTPUT, resume=True, rerun_failed=False, save_solutions=False,
                    command="scripts/run_candidate_v1_smoke.py", source_filename="results.jsonl")
    selected = {(row["identity"]["instance_id"], row["identity"]["configuration_name"]): row for row in rows}
    candidate_rows = [selected[("XS01", "algorithm-candidate-v1")], selected[("S01", "algorithm-candidate-v1")]]
    errors = {row["identity"]["instance_id"]: check_candidate(row) for row in candidate_rows}
    xs_candidate, xs_c2 = selected[("XS01", "algorithm-candidate-v1")], selected[("XS01", "C2_core_aggregate")]
    switch_match = all(xs_candidate["configuration"][key] == xs_c2["configuration"][key] for key in MATH_FIELDS)
    objective_match = (xs_candidate["optimization"]["ub"] is not None and xs_c2["optimization"]["ub"] is not None
                       and abs(xs_candidate["optimization"]["ub"] - xs_c2["optimization"]["ub"]) <= 1e-6)
    passed = not any(errors.values()) and switch_match and objective_match
    report = {"status": "PASS" if passed else "FAIL", "runs": 3, "candidate_hash": FROZEN_CANDIDATE_V1_HASH,
              "candidate_checks": errors, "xs01_c2_switch_match": switch_match,
              "xs01_c2_exact_objective_match": objective_match,
              "candidate_algorithm_frozen": True, "final_algorithm_frozen": False}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "smoke_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "smoke_report.md").write_text(
        "# Candidate-v1 smoke\n\n" + f"Status: **{report['status']}**\n\n"
        f"- Candidate hash: `{FROZEN_CANDIDATE_V1_HASH}`\n"
        f"- XS01 C2 switch match: {switch_match}\n- XS01 exact objective match: {objective_match}\n"
        f"- Candidate checks: {errors}\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

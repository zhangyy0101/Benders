"""Adaptive, time-boxed P3 confirmation for the P2-selected configurations."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from algorithm_configurations import get_algorithm_configuration
from experiment_runner import read_jsonl, run_jobs

INSTANCES = ("S01", "M01", "L01")
BUDGETS = {"S01": 30, "M01": 90, "L01": 240}
PAIR_LABELS = ("aggregate", "warm_bundle", "alns", "root_valid_bundle")
LOWER_IS_BETTER = ("ub", "gap", "primal_integral", "gap_integral", "time_to_first_feasible")


def finite(value):
    return value is not None and math.isfinite(float(value))


def write_csv(path, records, fallback):
    fields = list(records[0]) if records else fallback
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(records)


def selected_configs(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    configs = payload["recommended_confirmation_configs"]
    if not 4 <= len(configs) <= 6:
        raise RuntimeError(f"P3 requires 4-6 configurations, received {len(configs)}")
    return configs


def paired_variants(configs):
    pairs = []
    for label, candidate, baseline in zip(PAIR_LABELS, configs[1:], configs[:-1]):
        pairs.append((label, candidate, baseline))
    return pairs


def normalized_improvement(candidate, baseline, key):
    c, b = candidate["optimization"].get(key), baseline["optimization"].get(key)
    if not finite(c) or not finite(b):
        return None
    sign = -1 if key in LOWER_IS_BETTER else 1
    return sign * (float(c) - float(b)) / max(abs(float(b)), 1e-9)


def pair_record(label, candidate, baseline):
    cf = bool(candidate["status"]["feasible_incumbent_found"])
    bf = bool(baseline["status"]["feasible_incumbent_found"])
    improvements = {key: normalized_improvement(candidate, baseline, key)
                    for key in ("ub", "lb", "gap", "primal_integral", "gap_integral", "time_to_first_feasible")}
    performance = [improvements[key] for key in ("ub", "lb", "gap", "primal_integral", "gap_integral", "time_to_first_feasible") if improvements[key] is not None]
    score = 1.0 if cf and not bf else -1.0 if bf and not cf else statistics.median(performance) if performance else 0.0
    outcome = "win" if score > .01 else "loss" if score < -.01 else "tie"
    ct, bt = float(candidate["timing"]["wall_clock"]), float(baseline["timing"]["wall_clock"])
    return {
        "component_comparison": label,
        "instance_id": candidate["identity"]["instance_id"], "seed": candidate["identity"]["seed"],
        "budget": candidate["identity"]["budget"], "threads": candidate["identity"]["threads"],
        "protocol": candidate["identity"]["problem_protocol"],
        "candidate": candidate["configuration"]["configuration_name"], "baseline": baseline["configuration"]["configuration_name"],
        "candidate_feasible": cf, "baseline_feasible": bf,
        **{f"{key}_improvement": improvements[key] for key in improvements},
        "runtime_improvement": (bt - ct) / max(abs(bt), 1e-9),
        "composite_improvement": score, "outcome": outcome,
    }


def bootstrap_ci(values, key):
    if not values:
        return None, None
    rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    samples = [statistics.mean(rng.choices(values, k=len(values))) for _ in range(2000)]
    samples.sort()
    return samples[int(.025 * len(samples))], samples[int(.975 * len(samples))]


def summarize_pairs(records):
    summaries, borderline = [], []
    for label in dict.fromkeys(r["component_comparison"] for r in records):
        group = [r for r in records if r["component_comparison"] == label]
        values = [float(r["composite_improvement"]) for r in group]
        low, high = bootstrap_ci(values, label)
        wins = sum(r["outcome"] == "win" for r in group); losses = sum(r["outcome"] == "loss" for r in group)
        seed_signs = []
        for seed in sorted({int(r["seed"]) for r in group}):
            seed_values = [float(r["composite_improvement"]) for r in group if int(r["seed"]) == seed]
            seed_signs.append(1 if statistics.median(seed_values) > .01 else -1 if statistics.median(seed_values) < -.01 else 0)
        positive_sizes = {r["instance_id"] for r in group if float(r["composite_improvement"]) > .01}
        feasible_unstable = any(bool(r["candidate_feasible"]) != bool(r["baseline_feasible"]) for r in group)
        median = statistics.median(values); win_rate = wins / len(group)
        reasons = []
        if .4 <= win_rate <= .6: reasons.append("win/loss close to 50%")
        if 1 in seed_signs and -1 in seed_signs: reasons.append("seeds 0 and 1 disagree")
        if abs(median) <= .01: reasons.append("median delta close to zero")
        if len(positive_sizes) == 1: reasons.append("benefit appears at only one size")
        if feasible_unstable: reasons.append("feasible rate is unstable")
        if reasons: borderline.append({"component_comparison": label, "candidate": group[0]["candidate"], "baseline": group[0]["baseline"], "reasons": reasons})
        summaries.append({
            "component_comparison": label, "candidate": group[0]["candidate"], "baseline": group[0]["baseline"],
            "pairs": len(group), "wins": wins, "ties": sum(r["outcome"] == "tie" for r in group), "losses": losses,
            "win_rate": win_rate, "paired_mean": statistics.mean(values), "paired_median": median,
            "bootstrap_95_ci_low": low, "bootstrap_95_ci_high": high,
            "candidate_feasible_rate": sum(bool(r["candidate_feasible"]) for r in group) / len(group),
            "baseline_feasible_rate": sum(bool(r["baseline_feasible"]) for r in group) / len(group),
            "mean_runtime_improvement": statistics.mean(float(r["runtime_improvement"]) for r in group),
            "median_runtime_improvement": statistics.median(float(r["runtime_improvement"]) for r in group),
            **{f"mean_{key}_improvement": statistics.mean(float(r[f"{key}_improvement"]) for r in group if r[f"{key}_improvement"] is not None)
               if any(r[f"{key}_improvement"] is not None for r in group) else None
               for key in ("ub", "lb", "gap", "primal_integral", "gap_integral", "time_to_first_feasible")},
            **{f"median_{key}_improvement": statistics.median(float(r[f"{key}_improvement"]) for r in group if r[f"{key}_improvement"] is not None)
               if any(r[f"{key}_improvement"] is not None for r in group) else None
               for key in ("ub", "lb", "gap", "primal_integral", "gap_integral", "time_to_first_feasible")},
        })
    return summaries, borderline


def analyze(rows, configs, output, seed2_executed=()):
    keyed = {(r["identity"]["instance_id"], int(r["identity"]["seed"]), r["configuration"]["configuration_name"]): r for r in rows}
    first = []
    for r in rows:
        if int(r["identity"]["seed"]) not in (0, 1): continue
        first.append({"instance_id": r["identity"]["instance_id"], "seed": r["identity"]["seed"],
                      "configuration": r["configuration"]["configuration_name"], "status": r["status"]["status"],
                      "feasible": r["status"]["feasible_incumbent_found"], "ub": r["optimization"].get("ub"),
                      "lb": r["optimization"].get("lb"), "gap": r["optimization"].get("gap"),
                      "primal_integral": r["optimization"].get("primal_integral"), "gap_integral": r["optimization"].get("gap_integral"),
                      "time_to_first_feasible": r["optimization"].get("time_to_first_feasible"), "runtime": r["timing"].get("wall_clock")})
    write_csv(output / "first_round_summary.csv", first, ["instance_id", "seed", "configuration"])
    records, missing = [], []
    for label, candidate_name, baseline_name in paired_variants(configs):
        seeds = (0, 1, 2) if label in seed2_executed else (0, 1)
        for instance in INSTANCES:
            for seed in seeds:
                c, b = keyed.get((instance, seed, candidate_name)), keyed.get((instance, seed, baseline_name))
                if c is None or b is None:
                    missing.append({"component_comparison": label, "instance_id": instance, "seed": seed,
                                    "candidate": candidate_name, "baseline": baseline_name})
                else: records.append(pair_record(label, c, b))
    write_csv(output / "missing_pairs.csv", missing, ["component_comparison", "instance_id", "seed", "candidate", "baseline"])
    summaries, borderline = summarize_pairs(records)
    write_csv(output / "paired_summary.csv", summaries, ["component_comparison"])
    return records, summaries, borderline, missing


def jobs_for(root, manifest, configs, seeds):
    selected = {r["instance_id"]: r for r in manifest["instances"] if r["instance_id"] in INSTANCES}
    jobs = []
    for instance in INSTANCES:
        row = selected[instance]
        for seed in seeds:
            for name in configs:
                jobs.append({"instance_id": instance, "instance_path": root / row["relative_path"], "expected_digest": row["digest"],
                             "seed": seed, "budget": BUDGETS[instance], "threads": 1, "mip_gap": .03, "alloc_domain": "integer",
                             "handling_rate_scale": 1.0, "outbound_policy": "proportional", "method": "bbc_candidate",
                             "configuration": get_algorithm_configuration(name)})
    return jobs


def write_recommendation(rows, configs, summaries, borderline, missing, seed2_labels, output):
    summary = {r["component_comparison"]: r for r in summaries}
    positive = lambda label: label in summary and float(summary[label]["paired_median"]) > .01 and float(summary[label]["candidate_feasible_rate"]) >= float(summary[label]["baseline_feasible_rate"])
    aggregate = positive("aggregate")
    warm_bundle = positive("warm_bundle")
    alns = positive("alns")
    root_valid = positive("root_valid_bundle")
    # P2 isolated analytic (drop), root (retain), and valid inequalities (retain); P3 confirms bundles only.
    retained_core = ["aggregate_recourse_lb"] if aggregate else []
    # The bundle is positive, but P2's isolated evidence favors valid inequalities.
    # Retaining root as well would exceed the two-strengthening structural limit.
    if root_valid: retained_core.append("valid_inequalities")
    retained_primal = ["alns"] if alns else ["warm_start"] if warm_bundle else []
    recommended = "algorithm-candidate-v1" if aggregate and root_valid else "C6_both_lb_warm_alns" if aggregate and alns else "C5_both_lb_warm" if aggregate and warm_bundle else "C2_core_aggregate" if aggregate else "C0_bbc_core"
    unresolved = bool(missing) or any(item["component_comparison"] not in seed2_labels for item in borderline)
    payload = {
        "recommended_candidate_configuration": recommended,
        "retained_core_components": retained_core,
        "retained_primal_module": retained_primal,
        "components_to_remove": [x for x in ("analytic_recourse_lb", "aggregate_recourse_lb" if not aggregate else None,
                                                "warm_start" if not warm_bundle else None, "alns" if not alns else None,
                                                "root_prepass", "valid_inequalities" if not root_valid else None) if x],
        "seed2_executed_for": list(seed2_labels), "actual_run_count": len(rows),
        "actual_runtime_seconds": sum(float(r["timing"]["wall_clock"]) for r in rows),
        "candidate_algorithm_frozen": False, "final_algorithm_frozen": False,
        "approved_for_candidate_freeze_review": not unresolved and not any(r["status"]["status"] == "EXCEPTION" for r in rows),
        "recommended_candidate_structure": {
            "bbc_core": True, "aggregate_recourse_lb": aggregate,
            "valid_inequalities": root_valid, "analytic_recourse_lb": False,
            "root_prepass": False, "warm_start": False, "alns": False
        },
        "interpretation_note": "C5 vs C2 combines analytic and warm; C8 vs C6 combines root and valid inequalities. P2 isolated evidence favors valid inequalities over root, and the two-strengthening limit prevents retaining both alongside aggregate.",
    }
    (output / "candidate_algorithm_recommendation.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    report = ["# P3 adaptive candidate confirmation", "", f"Recommended candidate structure: **{recommended}**", "",
              f"- Aggregate: {'retain for confirmation' if aggregate else 'drop from main line'}",
              "- Analytic: drop from main line",
              "- Root: drop from main line (structural limit and overlap)",
              f"- Warm: {'retain for confirmation' if warm_bundle else 'drop from main line'}",
              f"- ALNS: {'retain for confirmation' if alns else 'drop from main line'}",
              f"- Valid inequalities: {'retain for confirmation' if root_valid else 'drop from main line'}",
              f"- Seed 2 executed for: {', '.join(seed2_labels) or 'none'}", f"- Actual runs: {len(rows)}",
              f"- Actual runtime: {payload['actual_runtime_seconds']:.2f} seconds",
              f"- Exceptions: {sum(r['status']['status'] == 'EXCEPTION' for r in rows)}", "",
              "C5 vs C2 and C8 vs C6 are bundle comparisons; isolated component attribution is carried forward from P2 and is not presented as a new isolated P3 result.", "",
              "Bootstrap intervals describe stability only.", "",
              "`candidate_algorithm_frozen: false`; `final_algorithm_frozen: false`." ]
    (output / "component_confirmation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", default="experiments/internal_screen_fast/recommended_configs.json")
    parser.add_argument("--suite", default="benchmarks/paper_exp_v1_pilot21")
    parser.add_argument("--output", default="experiments/confirmatory_adaptive")
    parser.add_argument("--phase", choices=("first", "seed2", "analyze"), default="first")
    args = parser.parse_args(); configs = selected_configs(args.selection)
    root, output = Path(args.suite), Path(args.output); output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    raw = output / "raw_results.jsonl"
    if args.phase == "first":
        for job in jobs_for(root, manifest, configs, (0, 1)):
            rows = run_jobs([job], output, resume=True, rerun_failed=False, save_solutions=False, source_filename=raw.name)
            analyze(rows, configs, output)
            print(job["instance_id"], job["seed"], job["configuration"]["configuration_name"], flush=True)
    rows = read_jsonl(raw) if raw.exists() else []
    _, summaries, borderline, missing = analyze(rows, configs, output)
    optional = {"borderline_pairs": borderline, "jobs": []}
    for item in borderline:
        optional["jobs"].extend({"instance_id": instance, "seed": 2, "budget": BUDGETS[instance],
                                 "configuration": name, "component_comparison": item["component_comparison"]}
                                for instance in INSTANCES for name in (item["baseline"], item["candidate"]))
    (output / "optional_seed2_jobs.json").write_text(json.dumps(optional, indent=2) + "\n", encoding="utf-8")
    if args.phase == "seed2":
        labels = [item["component_comparison"] for item in borderline]
        names = list(dict.fromkeys(job["configuration"] for job in optional["jobs"]))
        for job in jobs_for(root, manifest, names, (2,)):
            rows = run_jobs([job], output, resume=True, rerun_failed=False, save_solutions=False, source_filename=raw.name)
            print(job["instance_id"], 2, job["configuration"]["configuration_name"], flush=True)
        _, summaries, _, missing = analyze(rows, configs, output, labels)
        write_recommendation(rows, configs, summaries, [], missing, labels, output)
    elif args.phase == "analyze":
        existing_seed2 = sorted({label for label, candidate, baseline in paired_variants(configs)
                                 if all((instance, 2, name) in {(r["identity"]["instance_id"], int(r["identity"]["seed"]), r["configuration"]["configuration_name"]) for r in rows}
                                        for instance in INSTANCES for name in (candidate, baseline))})
        _, summaries, remaining, missing = analyze(rows, configs, output, existing_seed2)
        write_recommendation(rows, configs, summaries, remaining, missing, existing_seed2, output)
    return 0


if __name__ == "__main__": raise SystemExit(main())

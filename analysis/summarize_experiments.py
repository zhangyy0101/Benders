"""Summarize experiment CSV files without mandatory statistical dependencies."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import FORMAL_SEEDS

SCENARIO_FIELDS = (
    "instance",
    "instance_bundle_sha256",
    "initial_utilization",
    "forecast_error",
    "forecast_error_mode",
    "outbound_rate",
    "time_limit",
)
DEFAULT_METRICS = (
    "ok",
    "total_wall_time",
    "realized_unplaced",
    "unplaced_rate",
    "fallback_rate",
    "mean_cycle_first_incumbent_wall_time",
    "final_global_repair_count",
    "global_repair_rate",
    "bottleneck_repair_trigger_rate",
    "bottleneck_selected_pair_block_count",
    "mean_bottleneck_selection_time",
    "aggregate_ladder_global_rate",
    "aggregate_ladder_safety_fallback_count",
    "aggregate_ladder_legacy_disagreement_count",
    "mean_aggregate_ladder_time",
    "mean_selected_aggregate_capacity_scale",
    "stability_cost",
    "revision_rate",
    "mean_cycle_normalized_operations_score",
    "mean_cycle_predicted_concentration_normalized",
    "mean_cycle_predicted_occupancy_balance_normalized",
    "mean_cycle_predicted_distance_normalized",
    "mean_cycle_predicted_in_out_conflict_normalized",
    "realized_distance",
    "realized_in_out_conflict",
    "mean_realized_bays_per_ship_pod",
    "max_realized_peak_block_utilization",
    "mean_realized_utilization_deviation",
    "propagation_trigger_rate",
    "mean_propagated_pair_count",
    "mean_dependency_edge_count",
    "mean_dependency_graph_time",
    "repair_trigger_rate",
    "quality_polish_trigger_rate",
    "quality_polish_improvement_rate",
    "max_variables",
    "max_binary_variables",
    "max_constraints",
    "mean_nodes",
    "mean_preprocessing_time",
    "mean_solver_time",
)

FIELD_ALIASES = {
    # rolling-v3.x called the normalized, dimensionless score a cost.
    "mean_cycle_normalized_operations_score": (
        "mean_cycle_predicted_operations_cost",
    ),
}

HIGHER_IS_BETTER = {
    "ok",
    "quality_polish_improvement_rate",
}


def _number(row: dict, field: str) -> float | None:
    try:
        value = row.get(field, "")
        if value in (None, ""):
            value = next(
                (
                    row.get(alias)
                    for alias in FIELD_ALIASES.get(field, ())
                    if row.get(alias) not in (None, "")
                ),
                "",
            )
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return 1.0 if value.lower() == "true" else 0.0
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def describe(values: list[float]) -> dict[str, float | int | None]:
    """Return deterministic descriptive statistics and a normal 95% CI."""
    if not values:
        return {"count": 0, "mean": None, "std": None, "median": None, "ci95": None}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    ci95 = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "mean": mean,
        "std": std,
        "median": statistics.median(values),
        "ci95": ci95,
    }


def method_label(row: dict) -> str:
    """Distinguish DRA sensitivity profiles without duplicating other methods."""
    configuration = str(row.get("configuration", ""))
    if configuration != "dra_rpm":
        return configuration
    profile = row.get("baseline_parameter_profile") or "frozen"
    return f"dra_rpm[{profile}]"


def paired_comparison(
    rows: list[dict],
    metric: str,
    left: str,
    right: str,
) -> dict:
    """Compare configurations on identical scenario and seed keys."""
    indexed = {}
    for row in rows:
        value = _number(row, metric)
        if value is None:
            continue
        key = tuple(row.get(field) for field in SCENARIO_FIELDS) + (row.get("seed"),)
        indexed[key, method_label(row)] = value
    differences = [
        indexed[key, left] - indexed[key, right]
        for key, configuration in sorted(
            indexed,
            key=lambda item: tuple(
                "" if value is None else str(value)
                for value in (*item[0], item[1])
            ),
        )
        if configuration == left and (key, right) in indexed
    ]
    tolerance = 1e-9
    left_lower = sum(value < -tolerance for value in differences)
    ties = sum(abs(value) <= tolerance for value in differences)
    left_higher = sum(value > tolerance for value in differences)
    higher_is_better = metric in HIGHER_IS_BETTER
    result = {
        "left": left,
        "right": right,
        "metric": metric,
        "difference_definition": "left - right",
        "differences": differences,
        "summary": describe(differences),
        "direction": "higher_is_better" if higher_is_better else "lower_is_better",
        "left_wins": left_higher if higher_is_better else left_lower,
        "ties": ties,
        "left_losses": left_lower if higher_is_better else left_higher,
        "wilcoxon": None,
        "wilcoxon_note": "scipy unavailable; pure-Python paired statistics reported",
    }
    try:
        from scipy.stats import wilcoxon  # type: ignore

        if differences and any(abs(value) > 1e-12 for value in differences):
            statistic, p_value = wilcoxon(differences)
            result["wilcoxon"] = {"statistic": float(statistic), "p_value": float(p_value)}
            result["wilcoxon_note"] = "two-sided scipy Wilcoxon signed-rank test"
    except ImportError:
        pass
    return result


def artifact_audit(rows: list[dict]) -> dict:
    """Check publication-critical row consistency without solver dependencies."""
    score_fields = (
        "mean_cycle_predicted_concentration_normalized",
        "mean_cycle_predicted_occupancy_balance_normalized",
        "mean_cycle_predicted_distance_normalized",
        "mean_cycle_predicted_in_out_conflict_normalized",
    )
    weight_fields = (
        "concentration",
        "balance",
        "distance",
        "in_out_conflict",
    )
    score_errors = []
    for row in rows:
        score = _number(row, "mean_cycle_normalized_operations_score")
        components = [_number(row, field) for field in score_fields]
        profile_value = row.get("weight_profile")
        try:
            profile = (
                json.loads(profile_value)
                if isinstance(profile_value, str)
                else profile_value
            ) or {}
            weights = profile.get("operations", {})
            coefficients = [float(weights[field]) for field in weight_fields]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            coefficients = []
        if score is None or any(value is None for value in components) or not coefficients:
            continue
        expected = sum(
            coefficient * component
            for coefficient, component in zip(coefficients, components)
        )
        score_errors.append(abs(score - expected))

    def unique(field: str) -> list[str]:
        return sorted({str(row[field]) for row in rows if row.get(field) not in (None, "")})

    formal_rows = [
        row for row in rows if row.get("experiment_phase") == "formal"
    ]
    identities = [
        (
            row.get("instance_bundle_sha256") or row.get("instance"),
            method_label(row),
            row.get("seed"),
            row.get("time_limit"),
        )
        for row in rows
    ]

    def valid_formal_seed(row: dict) -> bool:
        try:
            return int(row.get("seed", -1)) in FORMAL_SEEDS
        except (TypeError, ValueError):
            return False

    return {
        "row_count": len(rows),
        "failed_row_count": sum(_number(row, "ok") == 0 for row in rows),
        "validation_failure_count": sum(
            _number(row, "validation_failure_count") or 0 for row in rows
        ),
        "wall_clock_failure_count": sum(
            _number(row, "wall_clock_time_limit_exceeded") or 0 for row in rows
        ),
        "dirty_row_count": sum(
            str(row.get("git_dirty", "")).lower() == "true" for row in rows
        ),
        "duplicate_experiment_identity_count": (
            len(identities) - len(set(identities))
        ),
        "formal_row_count": len(formal_rows),
        "formal_missing_bundle_hash_count": sum(
            not row.get("instance_bundle_sha256") for row in formal_rows
        ),
        "formal_unexpected_seed_count": sum(
            not valid_formal_seed(row) for row in formal_rows
        ),
        "formal_provisional_public_source_count": sum(
            row.get("instance_family")
            == "public_data_calibrated_semi_synthetic"
            and str(row.get("source_publication_ready", "")).lower()
            != "true"
            for row in formal_rows
        ),
        "problem_protocols": unique("problem_protocol"),
        "algorithm_versions": unique("algorithm_version"),
        "result_schema_versions": unique("result_schema_version"),
        "experiment_phases": unique("experiment_phase"),
        "score_identity_checked_rows": len(score_errors),
        "score_identity_failure_count": sum(error > 1e-8 for error in score_errors),
        "max_score_identity_error": max(score_errors, default=None),
    }


def summarize(rows: list[dict], metrics: tuple[str, ...]) -> dict:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in SCENARIO_FIELDS) + (
            row.get("configuration"),
            row.get("baseline_parameter_profile"),
        )
        grouped[key].append(row)
    summaries = []
    for key, group in sorted(
        grouped.items(),
        key=lambda item: tuple(
            "" if value is None else str(value) for value in item[0]
        ),
    ):
        entry = {
            field: value
            for field, value in zip(SCENARIO_FIELDS, key[:-2])
        }
        entry["configuration"] = key[-2]
        entry["baseline_parameter_profile"] = key[-1]
        entry["method_label"] = method_label(group[0])
        entry["metrics"] = {
            metric: describe([
                value for row in group if (value := _number(row, metric)) is not None
            ])
            for metric in metrics
        }
        summaries.append(entry)
    comparison_pairs = (
        ("full_bottleneck", "core"),
        ("full_bottleneck", "core_start"),
        ("full_bottleneck", "core_start_impact"),
        ("full_bottleneck", "full_direct"),
        ("full_bottleneck", "kp_dos"),
        ("full_bottleneck", "kp_sg"),
        ("full_bottleneck", "dra_rpm[frozen]"),
        ("full_bottleneck", "full_bottleneck_no_aggregate"),
        ("full", "full_direct"),
        ("dra_rpm[mu_low]", "dra_rpm[frozen]"),
        ("dra_rpm[mu_high]", "dra_rpm[frozen]"),
        ("dra_rpm[nu_low]", "dra_rpm[frozen]"),
        ("dra_rpm[nu_high]", "dra_rpm[frozen]"),
        ("dra_rpm[discount_low]", "dra_rpm[frozen]"),
        ("dra_rpm[discount_high]", "dra_rpm[frozen]"),
    )
    comparisons = [
        paired_comparison(rows, metric, left, right)
        for metric in metrics
        for left, right in comparison_pairs
    ]
    return {
        "artifact_audit": artifact_audit(rows),
        "group_summaries": summaries,
        "paired_comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS))
    parser.add_argument("--output")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    with open(args.input, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    result = summarize(rows, tuple(args.metrics))
    manifest_path = Path(args.manifest) if args.manifest else Path(args.input).with_suffix(
        ".manifest.json"
    )
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        matrix = manifest.get("requested_matrix") or {}
        result["manifest_audit"] = {
            "path": str(manifest_path),
            "row_count": manifest.get("row_count"),
            "expected_row_count": manifest.get("expected_row_count"),
            "complete": manifest.get("complete"),
            "all_ok": manifest.get("all_ok"),
            "instance_index_count": len(
                matrix.get("instance_indexes") or []
            ),
            "time_budget_policy": matrix.get("time_budget_policy"),
        }
    else:
        result["manifest_audit"] = {"path": str(manifest_path), "present": False}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

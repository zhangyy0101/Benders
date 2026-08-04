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

PROTOCOL_FIELDS = (
    "problem_protocol",
    "algorithm_version",
    "result_schema_version",
    "git_commit",
)

SCENARIO_FIELDS = (
    "instance",
    "instance_bundle_sha256",
    "initial_utilization",
    "forecast_error",
    "forecast_error_mode",
    "outbound_rate",
    "time_limit",
    "operation_weight_profile",
)
PAIRING_FIELDS = PROTOCOL_FIELDS + (
    "instance",
    "instance_bundle_sha256",
    "num_blocks",
    "bays_per_block",
    "num_ships",
    "cycles",
    "tail_execution_cycles",
    "requested_initial_utilization",
    "ship_volume_factor",
    "oracle_case_class",
    "forecast_error",
    "forecast_error_mode",
    "outbound_rate",
    "release_delay_periods",
    "time_limit",
    "threads",
    "mip_gap",
    "dependency_profile",
    "operation_weight_profile",
)
DEFAULT_METRICS = (
    "ok",
    "total_online_decision_time",
    "total_audit_wall_time",
    "total_wall_time",
    "total_solution_extract_time",
    "total_model_dispose_time",
    "total_validation_time",
    "time_limit_feasible_count",
    "online_deadline_miss_count",
    "realized_unplaced",
    "unplaced_rate",
    "fallback_rate",
    "mean_cycle_first_incumbent_wall_time",
    "final_global_repair_count",
    "residual_shortage_global_repair_enqueued_count",
    "residual_shortage_global_repair_skipped_time_count",
    "restricted_build_timeout_global_repair_enqueued_count",
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


def _student_t_critical_95(degrees_of_freedom: int) -> float:
    """Return the two-sided 95% Student-t critical value."""
    try:
        from scipy.stats import t  # type: ignore

        return float(t.ppf(.975, degrees_of_freedom))
    except ImportError:
        # Exact enough for the small-sample range used by the frozen seed sets;
        # use the asymptotic normal value only beyond this fallback table.
        table = (
            12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306,
            2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120,
            2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
            2.060, 2.056, 2.052, 2.048, 2.045, 2.042,
        )
        return table[degrees_of_freedom - 1] if degrees_of_freedom <= 30 else 1.96


def describe(values: list[float]) -> dict[str, float | int | str | None]:
    """Return descriptive statistics and a two-sided Student-t 95% CI."""
    if not values:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "median": None,
            "ci95": None,
            "ci95_half_width": None,
            "ci95_lower": None,
            "ci95_upper": None,
            "ci95_method": "unavailable",
        }
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    ci95 = (
        _student_t_critical_95(len(values) - 1) * std / math.sqrt(len(values))
        if len(values) > 1 else 0.0
    )
    return {
        "count": len(values),
        "mean": mean,
        "std": std,
        "median": statistics.median(values),
        "ci95": ci95,
        "ci95_half_width": ci95,
        "ci95_lower": mean - ci95,
        "ci95_upper": mean + ci95,
        "ci95_method": "student_t" if len(values) > 1 else "single_observation",
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
        key = tuple(row.get(field) for field in PAIRING_FIELDS) + (row.get("seed"),)
        indexed_key = (key, method_label(row))
        if indexed_key in indexed:
            raise ValueError(
                "duplicate paired observation for metric "
                f"{metric}: method={indexed_key[1]!r}, key={key!r}"
            )
        indexed[indexed_key] = value
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
        "wilcoxon_note": "fewer than five nonzero paired differences",
    }
    try:
        from scipy.stats import wilcoxon  # type: ignore

        nonzero_count = sum(abs(value) > 1e-12 for value in differences)
        if len(differences) >= 5 and nonzero_count >= 5:
            statistic, p_value = wilcoxon(differences)
            result["wilcoxon"] = {
                "statistic": float(statistic),
                "p_value": float(p_value),
                "effective_pair_count": nonzero_count,
                "eligible": True,
            }
            result["wilcoxon_note"] = "two-sided scipy Wilcoxon signed-rank test"
    except ImportError:
        result["wilcoxon_note"] = "scipy unavailable; test not computed"
    return result


def apply_holm_correction(comparisons: list[dict]) -> None:
    """Apply Holm correction separately within each reported metric family."""
    families: dict[str, list[dict]] = defaultdict(list)
    for comparison in comparisons:
        if comparison.get("wilcoxon") is not None:
            families[str(comparison["metric"])].append(comparison)
    for family in families.values():
        ordered = sorted(family, key=lambda item: item["wilcoxon"]["p_value"])
        running = 0.0
        size = len(ordered)
        for rank, comparison in enumerate(ordered):
            adjusted = min(1.0, (size - rank) * comparison["wilcoxon"]["p_value"])
            running = max(running, adjusted)
            comparison["wilcoxon"]["p_value_holm"] = running
            comparison["wilcoxon"]["holm_family_size"] = size
            comparison["wilcoxon"]["significant_at_0_05_holm"] = running < .05


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
    score_checked_indexes: set[int] = set()
    for row_index, row in enumerate(rows):
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
        score_checked_indexes.add(row_index)

    def unique(field: str) -> list[str]:
        return sorted({str(row[field]) for row in rows if row.get(field) not in (None, "")})

    formal_rows = [
        row for row in rows if row.get("experiment_phase") == "formal"
    ]
    identities = [
        tuple(row.get(field) for field in PAIRING_FIELDS)
        + (method_label(row), row.get("seed"))
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
        "online_deadline_miss_count": sum(
            _number(row, "online_deadline_miss_count") or 0
            for row in rows
        ),
        "time_limit_feasible_count": sum(
            _number(row, "time_limit_feasible_count") or 0
            for row in rows
        ),
        "dirty_row_count": sum(
            str(row.get("git_dirty", "")).lower() == "true" for row in rows
        ),
        "missing_git_identity_count": sum(
            row.get("git_commit") in (None, "")
            or str(row.get("git_dirty", "")).lower() not in ("true", "false")
            for row in rows
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
        "formal_score_identity_unchecked_count": sum(
            index not in score_checked_indexes
            for index, row in enumerate(rows)
            if row.get("experiment_phase") == "formal"
        ),
        "problem_protocols": unique("problem_protocol"),
        "algorithm_versions": unique("algorithm_version"),
        "result_schema_versions": unique("result_schema_version"),
        "git_commits": unique("git_commit"),
        "experiment_phases": unique("experiment_phase"),
        "score_identity_checked_rows": len(score_errors),
        "score_identity_failure_count": sum(error > 1e-8 for error in score_errors),
        "max_score_identity_error": max(score_errors, default=None),
    }


def publication_consistency_errors(
    rows: list[dict],
    *,
    manifest: dict | None = None,
    require_manifest: bool = False,
    allow_mixed_protocols: bool = False,
) -> list[str]:
    """Return reasons why rows must not be used as publication evidence."""
    errors: list[str] = []
    audit = artifact_audit(rows)
    mixed = {
        field: sorted({str(row.get(field)) for row in rows if row.get(field) not in (None, "")})
        for field in PROTOCOL_FIELDS
    }
    if not allow_mixed_protocols:
        for field, values in mixed.items():
            if len(values) > 1:
                errors.append(f"mixed {field}: {values}")

    formal_rows = [row for row in rows if row.get("experiment_phase") == "formal"]
    if not formal_rows:
        return errors
    if len(formal_rows) != len(rows):
        errors.append("formal and non-formal rows are mixed")
    for field in PROTOCOL_FIELDS:
        missing = sum(row.get(field) in (None, "") for row in formal_rows)
        if missing:
            errors.append(f"formal rows missing {field}: {missing}")

    checks = (
        ("failed formal rows", sum(_number(row, "ok") != 1 for row in formal_rows)),
        (
            "formal validation failures",
            sum(_number(row, "validation_failure_count") != 0 for row in formal_rows),
        ),
        (
            "formal online deadline misses",
            sum(_number(row, "online_deadline_miss_count") != 0 for row in formal_rows),
        ),
        (
            "formal wall-clock failures",
            sum(_number(row, "wall_clock_time_limit_exceeded") != 0 for row in formal_rows),
        ),
        ("formal dirty rows", audit["dirty_row_count"]),
        ("formal missing Git identities", audit["missing_git_identity_count"]),
        ("duplicate experiment identities", audit["duplicate_experiment_identity_count"]),
        ("formal rows missing bundle hashes", audit["formal_missing_bundle_hash_count"]),
        ("formal rows with unexpected seeds", audit["formal_unexpected_seed_count"]),
        (
            "formal rows with provisional public sources",
            audit["formal_provisional_public_source_count"],
        ),
        ("normalized-score identity failures", audit["score_identity_failure_count"]),
        (
            "formal rows without normalized-score identity evidence",
            audit["formal_score_identity_unchecked_count"],
        ),
    )
    errors.extend(f"{label}: {count}" for label, count in checks if count)

    if require_manifest and manifest is None:
        errors.append("formal result manifest is missing")
    if manifest is not None:
        if manifest.get("complete") is not True:
            errors.append("formal result manifest is not complete")
        if manifest.get("all_ok") is not True:
            errors.append("formal result manifest does not report all_ok=true")
        try:
            if int(manifest.get("row_count", -1)) != len(rows):
                errors.append("manifest row_count differs from the CSV")
            if int(manifest.get("expected_row_count", -1)) != len(rows):
                errors.append("manifest expected_row_count differs from the CSV")
        except (TypeError, ValueError):
            errors.append("manifest row counts are invalid")
    return errors


def summarize(
    rows: list[dict],
    metrics: tuple[str, ...],
    *,
    strict_formal: bool | None = None,
    allow_mixed_protocols: bool = False,
) -> dict:
    if strict_formal is None:
        strict_formal = any(row.get("experiment_phase") == "formal" for row in rows)
    consistency_errors = publication_consistency_errors(
        rows,
        allow_mixed_protocols=allow_mixed_protocols,
    )
    if consistency_errors and (strict_formal or not allow_mixed_protocols):
        raise ValueError("publication consistency audit failed: " + "; ".join(consistency_errors))

    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in PROTOCOL_FIELDS + SCENARIO_FIELDS) + (
            row.get("threads"),
            row.get("mip_gap"),
            row.get("dependency_profile"),
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
            for field, value in zip(
                PROTOCOL_FIELDS + SCENARIO_FIELDS + (
                    "threads", "mip_gap", "dependency_profile"
                ),
                key[:-2],
            )
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
    apply_holm_correction(comparisons)
    return {
        "artifact_audit": artifact_audit(rows),
        "publication_consistency_errors": consistency_errors,
        "strict_formal_audit": bool(strict_formal),
        "group_summaries": summaries,
        "paired_comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS))
    parser.add_argument("--output")
    parser.add_argument("--manifest")
    parser.add_argument(
        "--exploratory",
        action="store_true",
        help="allow mixed/incomplete artifacts and label the output non-publication",
    )
    args = parser.parse_args()
    with open(args.input, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    manifest_path = Path(args.manifest) if args.manifest else Path(args.input).with_suffix(
        ".manifest.json"
    )
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists() else None
    )
    formal = any(row.get("experiment_phase") == "formal" for row in rows)
    if formal and not args.exploratory:
        errors = publication_consistency_errors(
            rows,
            manifest=manifest,
            require_manifest=True,
        )
        if errors:
            parser.error("formal publication audit failed: " + "; ".join(errors))
    try:
        result = summarize(
            rows,
            tuple(args.metrics),
            strict_formal=formal and not args.exploratory,
            allow_mixed_protocols=args.exploratory,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result["analysis_mode"] = "exploratory" if args.exploratory else "publication"
    if manifest_path.exists():
        assert manifest is not None
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

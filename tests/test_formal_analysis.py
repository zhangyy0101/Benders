import json
import unittest

from config import (
    ALGORITHM_VERSION,
    FORMAL_SEEDS,
    PROBLEM_PROTOCOL,
    RESULT_SCHEMA_VERSION,
)
from analysis.summarize_experiments import (
    DEFAULT_METRICS,
    artifact_audit,
    describe,
    method_label,
    paired_comparison,
    publication_consistency_errors,
    summarize,
)


def _row(
    configuration: str,
    value: float,
    *,
    profile: str = "not_applicable",
    seed: int = FORMAL_SEEDS[0],
    scenario: str = "case",
):
    is_literature_baseline = configuration in {"kp_dos", "kp_sg", "dra_rpm"}
    return {
        "instance": f"{scenario}_seed{seed}",
        "instance_bundle_sha256": "abc",
        "instance_family": "reproducible_synthetic",
        "initial_utilization": "0.5",
        "forecast_error": "0.1",
        "forecast_error_mode": "mixed",
        "outbound_rate": "150",
        "time_limit": "20",
        "configuration": configuration,
        "baseline_protocol": (
            "adapted-literature-baselines-v1.1-sparse-cached"
            if is_literature_baseline else None
        ),
        "stability_formulation": (
            "common_ex_post_accounting"
            if is_literature_baseline else "epigraph_only"
        ),
        "baseline_parameter_profile": profile,
        "seed": str(seed),
        "ok": "True",
        "realized_unplaced": str(value),
        "experiment_phase": "formal",
        "git_dirty": "False",
        "problem_protocol": PROBLEM_PROTOCOL,
        "algorithm_version": ALGORITHM_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "git_commit": "0123456789abcdef",
        "validation_failure_count": "0",
        "online_deadline_miss_count": "0",
        "wall_clock_time_limit_exceeded": "0",
        "threads": "1",
        "mip_gap": ".01",
        "dependency_profile": "current",
        "operation_weight_profile": "business",
        "weight_profile": json.dumps({
            "operations": {
                "concentration": .2,
                "balance": .3,
                "distance": .4,
                "in_out_conflict": .1,
            }
        }),
        "mean_cycle_normalized_operations_score": "0",
        "mean_cycle_predicted_concentration_normalized": "0",
        "mean_cycle_predicted_occupancy_balance_normalized": "0",
        "mean_cycle_predicted_distance_normalized": "0",
        "mean_cycle_predicted_in_out_conflict_normalized": "0",
    }


class FormalAnalysisTests(unittest.TestCase):
    def test_default_metrics_include_execution_recovery_funnel(self):
        for metric in (
            "planned_infeasible_quantity",
            "fallback_placement",
            "pre_physical_recovery_unplaced",
            "physical_recovery_placement",
            "physical_recovery_displaced_reservation",
            "realized_unplaced",
        ):
            self.assertIn(metric, DEFAULT_METRICS)

    def test_small_sample_interval_uses_student_t(self):
        result = describe([1.0, 2.0])
        self.assertEqual(result["ci95_method"], "student_t")
        self.assertGreater(result["ci95_half_width"], 1.96 / 2**.5)
        self.assertAlmostEqual(
            result["ci95_upper"] - result["mean"],
            result["ci95_half_width"],
        )

    def test_dra_parameter_profiles_have_distinct_method_labels(self):
        self.assertEqual(
            method_label(_row("dra_rpm", 1, profile="mu_low")),
            "dra_rpm[mu_low]",
        )
        rows = [
            _row("dra_rpm", 2, profile="frozen"),
            _row("dra_rpm", 1, profile="mu_low"),
        ]
        result = paired_comparison(
            rows,
            "realized_unplaced",
            "dra_rpm[mu_low]",
            "dra_rpm[frozen]",
        )
        self.assertEqual(result["differences"], [-1.0])
        self.assertEqual(result["left_wins"], 1)
        groups = summarize(rows, ("realized_unplaced",))["group_summaries"]
        self.assertEqual(len(groups), 2)

    def test_duplicate_paired_observations_are_rejected(self):
        rows = [_row("core", 1), _row("core", 2)]
        with self.assertRaisesRegex(ValueError, "duplicate paired observation"):
            paired_comparison(rows, "realized_unplaced", "core", "full_bottleneck")

    def test_formal_summary_rejects_mixed_algorithm_versions(self):
        rows = [
            _row("core", 1),
            {**_row("full_bottleneck", 0), "algorithm_version": "old"},
        ]
        with self.assertRaisesRegex(ValueError, "mixed algorithm_version"):
            summarize(rows, ("realized_unplaced",))

    def test_wilcoxon_reports_holm_adjusted_probability_when_eligible(self):
        rows = []
        for seed in FORMAL_SEEDS[:6]:
            rows.extend([
                _row("full_bottleneck", 0, seed=seed),
                _row("core", 1, seed=seed),
            ])
        result = summarize(rows, ("realized_unplaced",))
        comparison = next(
            item for item in result["paired_comparisons"]
            if item["left"] == "full_bottleneck" and item["right"] == "core"
        )
        self.assertTrue(comparison["wilcoxon"]["eligible"])
        self.assertIn("p_value_holm", comparison["wilcoxon"])
        self.assertEqual(
            comparison["wilcoxon"]["holm_scope"],
            "scenario_cell_and_metric_family",
        )

    def test_confirmatory_inference_does_not_pool_scenario_cells(self):
        rows = []
        for scenario in ("small_ordinary", "large_pressure"):
            for seed in FORMAL_SEEDS[:6]:
                rows.extend([
                    _row("full_bottleneck", 0, seed=seed, scenario=scenario),
                    _row("core", 1, seed=seed, scenario=scenario),
                ])
        result = summarize(rows, ("realized_unplaced",))
        comparisons = [
            item for item in result["paired_comparisons"]
            if item["left"] == "full_bottleneck" and item["right"] == "core"
        ]
        self.assertEqual(len(comparisons), 2)
        self.assertEqual(
            {item["summary"]["count"] for item in comparisons},
            {6},
        )
        self.assertFalse(result["cross_cell_pooling_for_inference"])

    def test_algorithmic_failure_is_retained_but_quality_is_excluded(self):
        failed = {
            **_row("full_bottleneck", 5),
            "ok": "False",
            "online_deadline_miss_count": "1",
        }
        valid = _row("core", 0)
        rows = [failed, valid]
        manifest = {
            "complete": True,
            "all_ok": False,
            "row_count": 2,
            "expected_row_count": 2,
        }
        self.assertEqual(
            publication_consistency_errors(
                rows, manifest=manifest, require_manifest=True
            ),
            [],
        )
        result = summarize(rows, ("realized_unplaced", "ok"))
        failed_group = next(
            item for item in result["group_summaries"]
            if item["configuration"] == "full_bottleneck"
        )
        self.assertEqual(failed_group["invalid_quality_row_count"], 1)
        self.assertEqual(
            failed_group["metrics"]["realized_unplaced"]["count"], 0
        )
        self.assertEqual(failed_group["metrics"]["ok"]["count"], 1)

    def test_formal_artifact_audit_checks_bundle_seed_and_public_source(self):
        rows = [_row("full_bottleneck", 0)]
        rows.append({
            **_row("core", 0),
            "instance": "public_seed999",
            "instance_bundle_sha256": "",
            "instance_family": "public_data_calibrated_semi_synthetic",
            "source_publication_ready": "False",
            "seed": "999",
        })
        audit = artifact_audit(rows)
        self.assertEqual(audit["formal_row_count"], 2)
        self.assertEqual(audit["formal_missing_bundle_hash_count"], 1)
        self.assertEqual(audit["formal_unexpected_seed_count"], 1)
        self.assertEqual(audit["formal_provisional_public_source_count"], 1)

    def test_formal_audit_rejects_method_mismatched_stability_accounting(self):
        rows = [
            {
                **_row("kp_dos", 0),
                "stability_formulation": "epigraph_only",
            }
        ]
        audit = artifact_audit(rows)
        self.assertEqual(
            audit["formal_stability_formulation_mismatch_count"], 1
        )
        with self.assertRaisesRegex(
            ValueError,
            "mismatched stability formulation",
        ):
            summarize(rows, ("realized_unplaced",))


if __name__ == "__main__":
    unittest.main()

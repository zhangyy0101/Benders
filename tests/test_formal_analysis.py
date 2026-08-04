import json
import unittest

from config import ALGORITHM_VERSION, PROBLEM_PROTOCOL, RESULT_SCHEMA_VERSION
from analysis.summarize_experiments import (
    artifact_audit,
    describe,
    method_label,
    paired_comparison,
    summarize,
)


def _row(
    configuration: str,
    value: float,
    *,
    profile: str = "not_applicable",
    seed: int = 1000,
):
    return {
        "instance": "case_seed1000",
        "instance_bundle_sha256": "abc",
        "instance_family": "reproducible_synthetic",
        "initial_utilization": "0.5",
        "forecast_error": "0.1",
        "forecast_error_mode": "mixed",
        "outbound_rate": "150",
        "time_limit": "20",
        "configuration": configuration,
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
        for seed in range(1000, 1006):
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


if __name__ == "__main__":
    unittest.main()

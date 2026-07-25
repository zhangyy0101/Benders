import unittest

from analysis.summarize_experiments import (
    artifact_audit,
    method_label,
    paired_comparison,
    summarize,
)


def _row(configuration: str, value: float, *, profile: str = "not_applicable"):
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
        "seed": "1000",
        "ok": "True",
        "realized_unplaced": str(value),
        "experiment_phase": "formal",
        "git_dirty": "False",
        "result_schema_version": "rolling-results-v6",
    }


class FormalAnalysisTests(unittest.TestCase):
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

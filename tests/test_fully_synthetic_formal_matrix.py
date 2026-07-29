import json
import unittest
from pathlib import Path

import config


class FullySyntheticFormalMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path("docs/specs/fully_synthetic_formal_matrix_v1.json")
        cls.spec = json.loads(cls.path.read_text(encoding="utf-8"))

    def test_seed_and_protocol_boundary_is_frozen(self):
        self.assertEqual(
            tuple(self.spec["formal_seeds"]),
            tuple(config.FORMAL_SEEDS),
        )
        common = self.spec["common"]
        self.assertEqual(common["algorithm_version"], config.ALGORITHM_VERSION)
        self.assertEqual(common["problem_protocol"], config.PROBLEM_PROTOCOL)
        self.assertEqual(
            common["result_schema"], config.RESULT_SCHEMA_VERSION
        )
        self.assertTrue(common["sequential_shared_workstation"])

    def test_panel_and_result_counts_reconcile(self):
        panels = {row["panel"]: row for row in self.spec["panels"]}
        self.assertEqual(
            set(panels),
            {
                "scale_pressure",
                "initial_utilization",
                "forecast_error",
                "internal_ablation",
                "aggregate_ablation",
                "repair_mechanism",
            },
        )
        performance = sum(
            row["expected_result_rows"]
            for row in panels.values()
            if row["panel"] != "repair_mechanism"
        )
        mechanism = panels["repair_mechanism"]["expected_result_rows"]
        self.assertEqual(performance, 680)
        self.assertEqual(mechanism, 60)
        self.assertEqual(
            performance + mechanism,
            self.spec["counts"]["expected_total_result_rows"],
        )

    def test_forecast_profiles_are_unique_and_overlap_is_explicit(self):
        panel = next(
            row for row in self.spec["panels"]
            if row["panel"] == "forecast_error"
        )
        profiles = panel["magnitude_profiles"] + panel[
            "mechanism_profiles_at_error_010"
        ]
        identities = {
            (row["forecast_error"], row["forecast_error_mode"])
            for row in profiles
        }
        self.assertEqual(len(identities), 8)
        self.assertEqual(panel["unique_profile_count"], 8)
        self.assertEqual(panel["bundle_count"], 80)
        self.assertEqual(panel["existing_bundle_count"], 10)
        self.assertEqual(panel["missing_bundle_count"], 70)
        self.assertEqual(
            len(panel["profiles_to_generate"]) * len(config.FORMAL_SEEDS),
            panel["missing_bundle_count"],
        )

    def test_method_counts_match_expected_rows(self):
        for panel in self.spec["panels"]:
            self.assertEqual(
                panel["bundle_count"] * len(panel["methods"]),
                panel["expected_result_rows"],
            )


if __name__ == "__main__":
    unittest.main()

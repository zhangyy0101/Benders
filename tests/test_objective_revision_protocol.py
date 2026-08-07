import json
import unittest
from pathlib import Path

import config


class ObjectiveRevisionProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            Path("docs/specs/formal_run_manifest_v3.json").read_text(
                encoding="utf-8"
            )
        )

    def test_planned_revision_matches_current_implementation(self):
        revision = self.manifest["planned_revision"]
        self.assertEqual(revision["problem_protocol"], config.PROBLEM_PROTOCOL)
        self.assertEqual(revision["algorithm_version"], config.ALGORITHM_VERSION)
        self.assertEqual(revision["result_schema"], config.RESULT_SCHEMA_VERSION)
        self.assertEqual(
            revision["normalization"],
            config.OPERATION_OBJECTIVE_NORMALIZATION,
        )
        self.assertEqual(
            revision["primary_operation_weight_profile"],
            config.OPERATION_WEIGHT_PROFILE,
        )

    def test_prespecified_profiles_match_configuration(self):
        manifest_profiles = self.manifest["operation_weight_profiles"]
        self.assertEqual(set(manifest_profiles), set(config.OPERATION_WEIGHT_PROFILES))
        for name, configured in config.OPERATION_WEIGHT_PROFILES.items():
            self.assertEqual(manifest_profiles[name], {
                "distance": configured["distance"],
                "balance": configured["balance"],
                "concentration": configured["concentration"],
                "in_out_conflict": configured["in_out_conflict"],
            })
            self.assertAlmostEqual(sum(configured.values()), 1.0)
        business = config.OPERATION_WEIGHT_PROFILES["business"]
        self.assertGreater(business["distance"], business["balance"])
        self.assertGreater(business["balance"], business["concentration"])
        self.assertGreater(
            business["concentration"], business["in_out_conflict"]
        )

    def test_registered_confirmatory_set_is_formally_authorized(self):
        self.assertTrue(self.manifest["freeze_authorization"])
        self.assertTrue(config.FORMAL_RESULT_AUTHORIZED)
        self.assertFalse(
            self.manifest["evaluation_boundary"][
                "new_untouched_confirmatory_set_required"
            ]
        )
        confirmatory = self.manifest["evaluation_boundary"]["confirmatory_set"]
        self.assertEqual(tuple(confirmatory["seeds"]), config.FORMAL_SEEDS)
        self.assertTrue(confirmatory["registered_before_generation"])
        self.assertEqual(confirmatory["generated_bundle_count_at_registration"], 0)
        self.assertTrue(
            set(config.FORMAL_SEEDS).isdisjoint(config.HISTORICAL_FORMAL_SEEDS)
        )

    def test_confirmatory_matrix_and_statistics_are_prespecified(self):
        plan = self.manifest["confirmatory_formal_plan"]
        self.assertEqual(plan["expected_total_result_rows"], 1050)
        self.assertEqual(plan["execution_mode"], "sequential_single_process_on_exclusive_host")
        policy = self.manifest["publication_analysis_policy"]
        self.assertFalse(policy["cross_cell_pooling_for_inference"])
        self.assertEqual(
            policy["independent_replication_unit"],
            "seed within one prespecified scenario cell",
        )
        self.assertTrue(self.manifest["formal_failure_policy"]["retain_every_requested_row"])
        self.assertFalse(self.manifest["formal_failure_policy"]["selective_rerun"])

    def test_stability_is_objective_only_without_a_hard_budget(self):
        self.assertEqual(
            self.manifest["planned_revision"]["stability_policy"],
            "second lexicographic objective only; no hard stability budget in any domain",
        )
        self.assertNotIn("STABILITY_BASE_RATIO", vars(config))
        self.assertNotIn("STABILITY_CHANGE_RATIO", vars(config))


if __name__ == "__main__":
    unittest.main()

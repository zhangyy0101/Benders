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

    def test_revision_is_not_yet_formally_authorized(self):
        self.assertFalse(self.manifest["freeze_authorization"])
        self.assertFalse(config.FORMAL_RESULT_AUTHORIZED)
        self.assertTrue(
            self.manifest["evaluation_boundary"][
                "new_untouched_confirmatory_set_required"
            ]
        )


if __name__ == "__main__":
    unittest.main()

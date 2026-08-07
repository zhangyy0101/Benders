import json
import unittest
from pathlib import Path

import config
from scripts.prepare_tre_v3_formal_instances import (
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT,
    DEFAULT_PNC_SPEC,
    DEFAULT_SYNTHETIC_SPEC,
    generation_commands,
    load_design,
)


class TreV3FormalPreparationTests(unittest.TestCase):
    def test_registered_design_reconciles_without_opening_seeds(self):
        pnc, synthetic, manifest = load_design(
            DEFAULT_PNC_SPEC,
            DEFAULT_SYNTHETIC_SPEC,
            DEFAULT_MANIFEST,
        )
        self.assertEqual(tuple(pnc["formal_seeds"]), config.FORMAL_SEEDS)
        self.assertEqual(tuple(synthetic["formal_seeds"]), config.FORMAL_SEEDS)
        self.assertEqual(
            manifest["confirmatory_formal_plan"]["expected_total_result_rows"],
            1050,
        )
        self.assertFalse(DEFAULT_OUTPUT.exists())

    def test_generation_plan_is_complete_and_explicitly_guarded(self):
        commands = generation_commands(Path("unused-output"), 60.0)
        self.assertEqual(len(commands), 13)
        for command in commands:
            self.assertIn("--confirm-open-formal-seeds", command)
        rendered = [" ".join(command) for command in commands]
        self.assertEqual(sum("scale_pressure" in item for item in rendered), 1)
        self.assertEqual(
            sum("initial_utilization_" in item for item in rendered), 3
        )
        self.assertEqual(sum("forecast_error" in item for item in rendered), 7)
        self.assertEqual(sum("repair_mechanism" in item for item in rendered), 1)

    def test_execution_plan_reconciles_all_frozen_batches(self):
        plan = json.loads(
            Path("docs/specs/tre_v3_formal_execution_plan.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tuple(plan["formal_seeds"]), config.FORMAL_SEEDS)
        self.assertEqual(
            plan["formal_freeze_tag"], config.FORMAL_FREEZE_TAG
        )
        self.assertEqual(
            plan["execution"]["mode"], config.FORMAL_EXECUTION_MODE
        )
        batches = plan["batches"]
        self.assertEqual(
            [row["order"] for row in batches], list(range(1, 13))
        )
        self.assertEqual(
            sum(row["expected_rows"] for row in batches),
            plan["expected_total_rows"],
        )
        self.assertEqual(plan["expected_total_rows"], 1050)
        dra = next(row for row in batches if row["name"] == "dra_parameter_sensitivity")
        self.assertEqual(
            tuple(dra["baseline_parameter_profiles"]),
            config.FORMAL_DRA_SENSITIVITY_PROFILES,
        )


if __name__ == "__main__":
    unittest.main()

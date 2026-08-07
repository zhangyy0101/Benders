import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from scripts.prepare_pnc_yangshan_v2_formal_instances import (
    DATA_PROTOCOL,
    EXPECTED_PREFLIGHT_SHA256,
    PROFILE_ORDER,
    load_and_validate_spec,
    main as prepare_formal_main,
    profile_arguments,
    validate_preflight,
)
from scripts.prepare_pnc_yangshan_v3_confirmatory_instances import (
    load_confirmatory_spec,
)


class PncYangshanFormalFreezeTests(unittest.TestCase):
    def test_formal_generator_refuses_to_open_seeds_without_authorization(self):
        with mock.patch(
            "sys.argv",
            ["prepare_pnc_yangshan_v2_formal_instances.py"],
        ), mock.patch.object(config, "FORMAL_RESULT_AUTHORIZED", False):
            with self.assertRaises(SystemExit) as raised:
                prepare_formal_main()
        self.assertEqual(raised.exception.code, 2)

    def test_repository_spec_matches_frozen_configuration(self):
        spec = load_and_validate_spec(
            Path("docs/specs/pnc_yangshan_v2_formal_instance_spec.json")
        )
        self.assertEqual(
            tuple(spec["formal_seeds"]), config.HISTORICAL_FORMAL_SEEDS
        )
        self.assertEqual(
            tuple(row["profile"] for row in spec["profiles"]), PROFILE_ORDER
        )
        self.assertEqual(spec["expected_counts"]["unique_bundle_count"], 80)

    def test_preflight_gate_requires_complete_five_method_matrix(self):
        audit = {
            "status": "PASS",
            "row_count": 120,
            "instance_count": 24,
            "all_ok": True,
            "total_final_unplaced": 0,
            "validation_failures": 0,
            "online_deadline_misses": 0,
            "candidate_algorithm_version": config.ALGORITHM_VERSION,
            "external_baseline_protocol": config.EXTERNAL_BASELINE_PROTOCOL,
            "merged_csv_sha256": EXPECTED_PREFLIGHT_SHA256,
            "methods": list(config.FORMAL_PRIMARY_CONFIGURATIONS),
            "rows_per_method": {
                name: 24 for name in config.FORMAL_PRIMARY_CONFIGURATIONS
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(json.dumps(audit), encoding="utf-8")
            self.assertEqual(validate_preflight(path), audit)
            audit["rows_per_method"]["kp_sg"] = 23
            path.write_text(json.dumps(audit), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                validate_preflight(path)

    def test_profile_arguments_freeze_model_and_yard_contract(self):
        profile = {
            "profile": "volume_high",
            "source_period": "2026_05",
            "source_window": ["2026-05-14", "2026-05-20"],
            "yard_profile": "capacity_relief_080",
        }
        arguments = profile_arguments(profile)
        self.assertIn("high", arguments)
        self.assertIn("40", arguments)
        self.assertIn("3.0", arguments)
        self.assertIn("0.1", arguments)
        self.assertIn("60", arguments)

    def test_v3_confirmatory_spec_registers_new_unopened_seeds(self):
        spec, base = load_confirmatory_spec(
            Path("docs/specs/pnc_yangshan_v3_confirmatory_instance_spec.json")
        )
        self.assertEqual(tuple(spec["formal_seeds"]), config.FORMAL_SEEDS)
        self.assertTrue(spec["seed_selection"]["registered_before_generation"])
        self.assertEqual(
            tuple(base["formal_seeds"]), config.HISTORICAL_FORMAL_SEEDS
        )
        self.assertEqual(spec["expected_counts"]["unique_bundle_count"], 80)
        self.assertEqual(
            spec["expected_counts"]["total_semisynthetic_result_rows"], 310
        )


if __name__ == "__main__":
    unittest.main()

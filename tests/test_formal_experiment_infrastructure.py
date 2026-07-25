import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import config
from external_baselines import (
    DRA_PARAMETER_PROFILES,
    baseline_row_metadata,
)
from formal_experiments import (
    INSTANCE_BUNDLE_SCHEMA,
    case_sha256,
    read_instance_bundle,
    verify_portmis_source,
    write_instance_bundle,
)
from run_experiments import planned_experiment_identity
from scripts.run_formal_matrix import _paths_from_indexes


class FormalExperimentInfrastructureTests(unittest.TestCase):
    def test_instance_bundle_round_trip_preserves_tuple_keys_and_sets(self):
        case = {
            "plain": 3,
            "tuple_keyed": {("B1", "S1", 2): 7},
            "tuple_value": ("STD", 20),
            "set_value": {"G2", "G1"},
            "nested": [{"x": {1, 2}}],
        }
        metadata = {
            "instance_id": "unit_seed100",
            "instance_family": "unit",
            "seed": 100,
            "time_budget_seconds": 1.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.instance.json"
            second = Path(directory) / "second.instance.json"
            identity = write_instance_bundle(
                first, case=case, metadata=metadata
            )
            write_instance_bundle(second, case=case, metadata=metadata)
            restored, restored_metadata = read_instance_bundle(first)
            raw = json.loads(first.read_text(encoding="utf-8"))
            second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
        self.assertEqual(restored, case)
        self.assertEqual(raw["bundle_schema"], INSTANCE_BUNDLE_SCHEMA)
        self.assertEqual(identity["instance_bundle_sha256"], second_hash)
        self.assertEqual(restored_metadata["instance_case_sha256"], case_sha256(case))

    def test_instance_bundle_rejects_case_hash_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.instance.json"
            write_instance_bundle(
                path,
                case={"value": 1},
                metadata={
                    "instance_id": "case",
                    "instance_family": "unit",
                    "seed": 100,
                    "time_budget_seconds": 1.0,
                },
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["case"]["items"][0][1] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "case hash mismatch"):
                read_instance_bundle(path)

    def test_instance_index_pins_exact_bundle_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "case.instance.json"
            identity = write_instance_bundle(
                bundle,
                case={"value": 1},
                metadata={
                    "instance_id": "case",
                    "instance_family": "unit",
                    "seed": 1000,
                    "time_budget_seconds": 1.0,
                },
            )
            index = root / "index.json"
            index.write_text(json.dumps({
                "index_schema": "rolling-instance-index-v1",
                "instance_protocol": "rolling-formal-instances-v1",
                "experiment_phase": "formal",
                "entry_count": 1,
                "entries": [{
                    **identity,
                    "instance_bundle_filename": bundle.name,
                }],
            }), encoding="utf-8")
            paths, expected, records = _paths_from_indexes(
                [str(index)], require_formal=True
            )
            self.assertEqual(paths, [bundle.resolve()])
            self.assertEqual(
                expected[bundle.resolve()]["instance_bundle_sha256"],
                identity["instance_bundle_sha256"],
            )
            self.assertEqual(len(records[0]["sha256"]), 64)
            bundle.write_bytes(bundle.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "bundle/index SHA-256"):
                _paths_from_indexes([str(index)], require_formal=True)

    def test_portmis_source_contract_verifies_hashes_and_blocks_provisional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibrated"
            calibration.mkdir()
            output = calibration / "calls.csv"
            output.write_text("call_id\nC1\n", encoding="utf-8")
            output_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            (calibration / "audit.json").write_text(
                json.dumps({
                    "calibration_status": "PASS",
                    "protocol_version": "test",
                    "scenario_assumptions": {"capacity_utilization": 0.85},
                }),
                encoding="utf-8",
            )
            (calibration / "manifest.json").write_text(
                json.dumps({
                    "outputs": {"calls.csv": {"sha256": output_hash}}
                }),
                encoding="utf-8",
            )
            raw = root / "raw.json"
            raw.write_text("[]\n", encoding="utf-8")
            raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
            source_manifest = root / "manifest.json"
            source_manifest.write_text(
                json.dumps({
                    "pilot_only_undocumented_endpoint": True,
                    "raw_files": {"raw.json": {"sha256": raw_hash}},
                }),
                encoding="utf-8",
            )
            verified = verify_portmis_source(calibration)
            with self.assertRaisesRegex(ValueError, "provisional"):
                verify_portmis_source(
                    calibration, require_publication_ready=True
                )
            source_manifest.write_text(
                json.dumps({
                    "schema": "portmis-fixed-source-snapshot-v1",
                    "publication_ready": True,
                    "pilot_only_undocumented_endpoint": False,
                    "official_data_page": "https://example.test/official",
                    "extraction_method": "fixed official export",
                    "query": {"start_date": "2025-01-01"},
                    "raw_files": {"raw.json": {"sha256": raw_hash}},
                }),
                encoding="utf-8",
            )
            formal = verify_portmis_source(
                calibration, require_publication_ready=True
            )
        self.assertFalse(verified["source_publication_ready"])
        self.assertTrue(formal["source_publication_ready"])
        self.assertEqual(len(verified["source_snapshot_sha256"]), 64)

    def test_formal_seed_and_budget_matrix_is_frozen(self):
        self.assertEqual(config.FORMAL_SEEDS, tuple(range(1000, 1010)))
        self.assertEqual(len(config.FORMAL_PRIMARY_CONFIGURATIONS), 7)
        self.assertLessEqual(max(config.FORMAL_TIME_BUDGETS_SECONDS.values()), 120)
        self.assertEqual(set(config.FORMAL_PUBLIC_WINDOWS), {
            "public_small",
            "public_medium",
            "public_large",
        })

    def test_dra_profiles_are_scalar_and_identity_separating(self):
        self.assertEqual(DRA_PARAMETER_PROFILES["frozen"]["mu"], 0.5)
        row = baseline_row_metadata("dra_rpm", "mu_low")
        self.assertEqual(row["baseline_parameter_profile"], "mu_low")
        self.assertEqual(row["baseline_mu"], 0.25)
        case = {
            "num_blocks": 1,
            "bays_per_block": 1,
            "num_ships": 1,
            "cycles": 1,
            "requested_initial_utilization": 0.0,
            "forecast_error": 0.1,
            "forecast_error_mode": "multiplicative",
            "nominal_outbound_rate_per_ship_period": 1,
            "release_delay_periods": 0,
        }
        frozen = planned_experiment_identity(
            "case",
            case,
            "dra_rpm",
            100,
            1,
            baseline_parameter_profile="frozen",
            instance_metadata={"instance_bundle_sha256": "a"},
        )
        low = planned_experiment_identity(
            "case",
            case,
            "dra_rpm",
            100,
            1,
            baseline_parameter_profile="mu_low",
            instance_metadata={"instance_bundle_sha256": "a"},
        )
        self.assertNotEqual(frozen, low)


if __name__ == "__main__":
    unittest.main()

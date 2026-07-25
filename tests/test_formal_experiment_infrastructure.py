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
from scripts.package_portmis_source import package_snapshot
from scripts.run_formal_matrix import _paths_from_indexes


class FormalExperimentInfrastructureTests(unittest.TestCase):
    def test_publication_source_registry_has_three_fixed_periods(self):
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "portmis_publication_source_registry.json"
        )
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["registry_schema"],
            "portmis-publication-source-registry-v1",
        )
        self.assertEqual(
            set(registry["entries"]),
            {"spring_2025_03", "summer_2025_07", "autumn_2025_11"},
        )
        for entry in registry["entries"].values():
            self.assertEqual(len(entry["source_manifest_sha256"]), 64)
            self.assertEqual(len(entry["source_snapshot_sha256"]), 64)
            self.assertEqual(
                len(entry["publication_archive"]["sha256"]),
                64,
            )
            self.assertGreater(entry["publication_archive"]["bytes"], 0)
            self.assertGreaterEqual(entry["primary_cluster_call_count"], 100)
            self.assertGreaterEqual(entry["complete_daily_cycles"], 20)

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
            source_calls = root / "primary_cluster_calls.csv"
            source_calls.write_text("call_id\nC1\n", encoding="utf-8")
            source_calls_hash = hashlib.sha256(
                source_calls.read_bytes()
            ).hexdigest()
            source_audit = root / "audit.json"
            source_audit.write_text('{"pilot_status":"PASS"}', encoding="utf-8")
            source_audit_hash = hashlib.sha256(
                source_audit.read_bytes()
            ).hexdigest()
            (root / "report.md").write_text("# source\n", encoding="utf-8")
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
                    "outputs": {"calls.csv": {"sha256": output_hash}},
                    "source": {
                        "primary_cluster_calls_sha256": source_calls_hash,
                        "pilot_audit_sha256": source_audit_hash,
                    },
                }),
                encoding="utf-8",
            )
            raw = root / "raw.json"
            raw.write_text("[]\n", encoding="utf-8")
            raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
            raw_out = root / "raw_out.json"
            raw_out.write_text("[]\n", encoding="utf-8")
            raw_out_hash = hashlib.sha256(raw_out.read_bytes()).hexdigest()
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
                    "publication_ready": True,
                    "pilot_only_undocumented_endpoint": False,
                    "raw_files": {"raw.json": {"sha256": raw_hash}},
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported schema"):
                verify_portmis_source(
                    calibration, require_publication_ready=True
                )
            official_data_page = "https://www.data.go.kr/data/1/openapi.do"
            official_file_page = "https://www.data.go.kr/data/2/fileData.do"
            content_url = (
                "https://new.portmis.go.kr/portmis/websquare/websquare.jsp"
                "?page=/portmis/w2/sp/vssl/vsch/view.xml"
            )
            transport_url = (
                "https://new.portmis.go.kr/portmis/sp/vssl/vsch/query.do"
            )
            evidence_payloads = {
                "official_openapi_catalog.json": json.dumps({
                    "url": official_data_page,
                    "license": "이용허락범위 제한 없음",
                    "creator": {"name": "해양수산부"},
                }, ensure_ascii=False).encode("utf-8"),
                "official_file_catalog.json": json.dumps({
                    "url": official_file_page,
                    "license": "이용허락범위 제한 없음",
                    "creator": {"name": "해양수산부"},
                }, ensure_ascii=False).encode("utf-8"),
                "official_openapi_page.html": (
                    b'{"name":"serviceKey","required":true}'
                ),
                "official_file_page.html": (
                    f'{{"contentUrl":"{content_url}"}}'.encode("utf-8")
                ),
                "official_portal_view.xml": (
                    b"<action>/sp/vssl/vsch/query.do</action>"
                ),
            }
            evidence = {}
            for name, payload in evidence_payloads.items():
                path = root / name
                path.write_bytes(payload)
                evidence[name] = {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            directions = {
                "inbound": {
                    "parameters": {"ibobprtSe": "1"},
                    "body_sha256": "1" * 64,
                },
                "outbound": {
                    "parameters": {"ibobprtSe": "2"},
                    "body_sha256": "2" * 64,
                },
            }
            raw_declaration = {
                "sha256": raw_hash,
                "bytes": raw.stat().st_size,
                "rows": 0,
                "direction": "inbound",
                "request_body_sha256": "1" * 64,
            }
            raw_out_declaration = {
                "sha256": raw_out_hash,
                "bytes": raw_out.stat().st_size,
                "rows": 0,
                "direction": "outbound",
                "request_body_sha256": "2" * 64,
            }
            raw_files = {
                "raw.json": raw_declaration,
                "raw_out.json": raw_out_declaration,
            }
            source_snapshot_sha256 = hashlib.sha256(
                json.dumps(
                    {
                        "requests": directions,
                        "raw_files": raw_files,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            source_manifest.write_text(
                json.dumps({
                    "schema": "portmis-fixed-source-snapshot-v2",
                    "publication_ready": True,
                    "pilot_only_undocumented_endpoint": False,
                    "acquisition_mode": "official_provider_portal_export",
                    "official_data_page": official_data_page,
                    "official_file_page": official_file_page,
                    "extraction_method": "fixed official provider export",
                    "portal_contract": {
                        "official_content_url": content_url,
                        "transport_url": transport_url,
                        "method": "POST",
                        "documented_openapi_used": False,
                        "transport_endpoint_status": (
                            "bound_to_archived_official_provider_ui"
                        ),
                    },
                    "query": {
                        "port_code": "020",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-31",
                        "directions": directions,
                    },
                    "raw_files": raw_files,
                    "standardized_files": {
                        "primary_cluster_calls.csv": {
                            "sha256": source_calls_hash,
                            "bytes": source_calls.stat().st_size,
                        },
                        "audit.json": {
                            "sha256": source_audit_hash,
                            "bytes": source_audit.stat().st_size,
                        },
                    },
                    "official_metadata_files": evidence,
                    "source_snapshot_sha256": source_snapshot_sha256,
                    "source_revision_policy": {
                        "archived_bytes_are_immutable": True,
                        "provider_corrections_require_new_snapshot": True,
                        "live_refetch_hash_is_not_a_reproducibility_requirement": True,
                    },
                    "data_coverage": {
                        "observed_from_portmis": ["vessel_call_identity"],
                        "not_observed_from_portmis": [
                            "per_call_export_box_volume",
                            "per_container_discharge_port",
                            "container_size_and_height",
                            "historical_booking_forecasts",
                            "yard_inventory_and_bay_layout",
                            "legacy_yard_allocation",
                        ],
                        "treatment": {"box_demand": "semi-synthetic"},
                    },
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            formal = verify_portmis_source(
                calibration, require_publication_ready=True
            )
            package = package_snapshot(
                source_dir=root,
                calibration_dir=calibration,
                output=root / "publication.zip",
            )
            self.assertEqual(
                package["archive_schema"],
                "portmis-publication-archive-v1",
            )
            self.assertEqual(len(package["archive_sha256"]), 64)
        self.assertFalse(verified["source_publication_ready"])
        self.assertTrue(formal["source_publication_ready"])
        self.assertEqual(
            formal["source_acquisition_mode"],
            "official_provider_portal_export",
        )
        self.assertEqual(len(formal["verified_official_metadata"]), 5)
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
        self.assertEqual(set(config.FORMAL_PUBLIC_TEMPORAL_WINDOWS), {
            "public_temporal_spring",
            "public_temporal_summer",
            "public_temporal_autumn",
        })
        self.assertEqual(
            set(config.FORMAL_PUBLIC_CALIBRATION_SCENARIOS),
            {
                "central",
                "utilization_low",
                "utilization_high",
                "export_split_low",
                "export_split_high",
                "forty_share_low",
                "forty_share_high",
                "high_cube_low",
                "high_cube_high",
            },
        )
        self.assertEqual(
            config.FORMAL_SYNTHETIC_PRESSURE_TARGETS,
            {"ordinary": 0.70, "high_pressure": 0.85},
        )
        self.assertEqual(
            config.FORMAL_SYNTHETIC_PRESSURE_TARGET_TOLERANCE,
            0.03,
        )
        self.assertEqual(
            config.FORMAL_SYNTHETIC_UTILIZATION_LEVELS,
            (0.25, 0.55, 0.65),
        )
        self.assertEqual(
            config.FORMAL_SYNTHETIC_UTILIZATION_SIZE,
            "medium",
        )

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

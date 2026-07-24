import copy
import unittest

from scripts.calibrate_portmis_demand import (
    CALIBRATION_PROTOCOL_VERSION,
    CalibrationConfig,
    bounded_proportional_allocation,
    calibrate_calls,
)


def _call(index: int, gross_tonnage: int) -> dict[str, str]:
    return {
        "call_id": f"CALL_{index:02d}",
        "vessel_id": f"VESSEL_{index:02d}",
        "callsign": f"CALLSIGN_{index:02d}",
        "vessel_name": f"VESSEL NAME {index:02d}",
        "entry_time": f"2025-07-{index + 1:02d}T01:00",
        "departure_time": f"2025-07-{index + 1:02d}T22:00",
        "gross_tonnage": str(gross_tonnage),
        "facility_name": f"신선대부두 {(index % 5) + 1}선석",
        "facility_cluster": "SINSUNDAE",
        "previous_port_country": "KR",
        "previous_port_code": "KRPUS",
        "previous_port_name": "BUSAN",
        "next_port_country": "CN",
        "next_port_code": "CNSHA",
        "next_port_name": "SHANGHAI",
        "inbound_loaded_cargo_tonnage": str(index),
        "outbound_loaded_cargo_tonnage": str(index * 1000),
    }


class PortmisDemandCalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            _call(1, 8_000),
            _call(2, 10_000),
            _call(3, 14_000),
            _call(4, 20_000),
        ]
        self.config = CalibrationConfig(
            design_capacity_teu_per_year=30_000,
            capacity_utilization=0.80,
            min_boxes_per_call=10,
            max_boxes_per_call=1_000,
            boxes_per_pod=100,
        )

    def test_bounded_allocation_is_exact_and_deterministic(self):
        allocation = bounded_proportional_allocation(
            19,
            [1.0, 2.0, 4.0],
            lower=[2, 2, 2],
            upper=[4, 8, 12],
            keys=["a", "b", "c"],
        )
        self.assertEqual(sum(allocation), 19)
        self.assertEqual(allocation, [4, 6, 9])

    def test_call_and_group_totals_reconcile(self):
        calls, groups, audit = calibrate_calls(
            self.rows,
            period_days=30,
            config=self.config,
        )
        self.assertEqual(audit["protocol_version"], CALIBRATION_PROTOCOL_VERSION)
        self.assertEqual(audit["calibration_status"], "PASS")
        self.assertTrue(all(audit["gates"].values()))
        self.assertEqual(
            sum(row["synthetic_export_boxes"] for row in calls),
            sum(row["boxes"] for row in groups),
        )
        self.assertEqual(
            sum(row["synthetic_export_teu"] for row in calls),
            sum(row["teu"] for row in groups),
        )
        self.assertFalse(
            any(
                row["size_ft"] == 20 and row["height_class"] == "HIGH"
                for row in groups
            )
        )

    def test_reported_cargo_tonnage_is_not_used(self):
        changed = copy.deepcopy(self.rows)
        for index, row in enumerate(changed):
            row["inbound_loaded_cargo_tonnage"] = str(10**9 + index)
            row["outbound_loaded_cargo_tonnage"] = str(2 * 10**9 + index)
        baseline_calls, baseline_groups, _ = calibrate_calls(
            self.rows,
            period_days=30,
            config=self.config,
        )
        changed_calls, changed_groups, _ = calibrate_calls(
            changed,
            period_days=30,
            config=self.config,
        )
        self.assertEqual(baseline_calls, changed_calls)
        self.assertEqual(baseline_groups, changed_groups)


if __name__ == "__main__":
    unittest.main()

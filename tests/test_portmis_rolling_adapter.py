import copy
import unittest

from scripts.run_portmis_end_to_end import (
    ADAPTER_PROTOCOL_VERSION,
    build_portmis_rolling_case,
    select_calibrated_calls,
)


def _call(
    index: int,
    *,
    entry: str,
    departure: str,
    boxes: int,
    berth: int,
) -> dict[str, str]:
    return {
        "call_id": f"CALL_{index:02d}",
        "vessel_id": f"VESSEL_{index:02d}",
        "callsign": f"CS{index:02d}",
        "vessel_name": f"VESSEL {index:02d}",
        "entry_time": entry,
        "departure_time": departure,
        "gross_tonnage": str(8_000 + index * 2_000),
        "facility_name": f"신선대부두 {berth}선석",
        "facility_cluster": "SINSUNDAE",
        "previous_port_country": "KR",
        "previous_port_code": "KRPUS",
        "previous_port_name": "BUSAN",
        "next_port_country": "CN",
        "next_port_code": "CNSHA",
        "next_port_name": "SHANGHAI",
        "synthetic_export_boxes": str(boxes),
        "synthetic_export_teu": str(boxes + round(boxes * 0.65)),
        "synthetic_pod_count": "2",
        "synthetic_20ft_boxes": str(boxes - round(boxes * 0.65)),
        "synthetic_40ft_boxes": str(round(boxes * 0.65)),
        "synthetic_40ft_high_cube_boxes": str(round(boxes * 0.35)),
        "gross_tonnage_weight_share": "0.333333",
        "demand_origin": "capacity_anchored_semi_synthetic",
    }


def _groups(call_id: str, boxes: int) -> list[dict[str, str]]:
    first = boxes // 2
    second = boxes - first
    return [
        {
            "call_id": call_id,
            "pod": "P01",
            "size_ft": "20",
            "height_class": "STD",
            "boxes": str(first),
            "teu": str(first),
            "field_origin": "semi_synthetic",
        },
        {
            "call_id": call_id,
            "pod": "P02",
            "size_ft": "40",
            "height_class": "HIGH",
            "boxes": str(second),
            "teu": str(2 * second),
            "field_origin": "semi_synthetic",
        },
    ]


class PortmisRollingAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = [
            _call(
                1,
                entry="2025-07-01T06:00",
                departure="2025-07-02T00:00",
                boxes=120,
                berth=1,
            ),
            _call(
                2,
                entry="2025-07-01T12:00",
                departure="2025-07-02T06:00",
                boxes=150,
                berth=3,
            ),
            _call(
                3,
                entry="2025-07-02T00:00",
                departure="2025-07-03T00:00",
                boxes=180,
                berth=5,
            ),
        ]
        self.groups = [
            row
            for call in self.calls
            for row in _groups(
                call["call_id"], int(call["synthetic_export_boxes"])
            )
        ]

    def test_adapter_preserves_lifecycle_and_integer_demand(self):
        case, audit = build_portmis_rolling_case(
            self.calls,
            self.groups,
            seed=17,
            forecast_error=0.0,
            initial_utilization=0.10,
        )
        self.assertEqual(
            audit["adapter_protocol_version"], ADAPTER_PROTOCOL_VERSION
        )
        self.assertTrue(all(audit["gates"].values()))
        self.assertEqual(sum(case["booking_flow"].values()), 450)
        self.assertEqual(case["booking_flow"], case["true_flow"])
        for ship in case["ships"]:
            self.assertEqual(
                case["eta_period"][ship]
                - case["receiving_start_period"][ship],
                12,
            )
            self.assertGreater(
                case["planned_ship_release_period"][ship],
                case["eta_period"][ship],
            )
        self.assertGreater(
            case["cycles"] * case["execution_periods"],
            max(case["realized_ship_release_period"].values()),
        )

    def test_vessel_next_port_is_not_used_as_container_pod(self):
        changed = copy.deepcopy(self.calls)
        for row in changed:
            row["next_port_country"] = "XX"
            row["next_port_code"] = "XXXXX"
            row["next_port_name"] = "NOT A CONTAINER POD"
        baseline, _ = build_portmis_rolling_case(
            self.calls,
            self.groups,
            seed=17,
            forecast_error=0.0,
            initial_utilization=0.10,
        )
        modified, _ = build_portmis_rolling_case(
            changed,
            self.groups,
            seed=17,
            forecast_error=0.0,
            initial_utilization=0.10,
        )
        self.assertEqual(baseline["group_attrs"], modified["group_attrs"])
        self.assertEqual(baseline["booking_flow"], modified["booking_flow"])
        self.assertEqual(baseline["distance"], modified["distance"])

    def test_call_selection_keeps_complete_group_totals(self):
        selected_calls, selected_groups = select_calibrated_calls(
            list(reversed(self.calls)),
            self.groups,
            max_calls=2,
            selection_offset=1,
        )
        selected_ids = {row["call_id"] for row in selected_calls}
        self.assertEqual(selected_ids, {"CALL_02", "CALL_03"})
        self.assertEqual(
            sum(int(row["synthetic_export_boxes"]) for row in selected_calls),
            sum(int(row["boxes"]) for row in selected_groups),
        )


if __name__ == "__main__":
    unittest.main()

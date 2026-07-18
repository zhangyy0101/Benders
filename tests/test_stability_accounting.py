import unittest

from config import (
    STABILITY_BLOCK_REALLOCATION_WEIGHT,
    STABILITY_CANCEL_WEIGHT,
    STABILITY_NEW_BAY_WEIGHT,
)
from rolling_solver import canonical_stability_metrics


class StabilityAccountingTest(unittest.TestCase):
    def setUp(self):
        self.data = {
            "blocks": ["K1", "K2"],
            "bay_block": {"Y1": "K1", "Y2": "K2"},
            "group_attrs": {"G": {"pod": "P", "size": 20, "height": "STD"}},
            "previous_reservation": {("Y1", "V", "G"): 10},
            "actual_inventory": {},
            "remaining_demand": {("V", "G"): 10},
        }

    def test_mandatory_reduction_does_not_consume_discretionary_budget(self):
        self.data["remaining_demand"] = {("V", "G"): 7}
        metrics = canonical_stability_metrics(
            self.data, {("Y1", "V", "G"): 7}, {("V", "G", 0): 0}
        )
        self.assertEqual(metrics["cancellation_quantity"], 3)
        self.assertEqual(metrics["mandatory_reduction"], 3)
        self.assertEqual(metrics["discretionary_cancel"], 0)

    def test_cross_block_move_and_new_bay_are_separate(self):
        metrics = canonical_stability_metrics(
            self.data, {("Y2", "V", "G"): 10}, {("V", "G", 0): 0}
        )
        self.assertEqual(metrics["cancellation_quantity"], 10)
        self.assertEqual(metrics["block_reallocation_quantity"], 10)
        self.assertEqual(metrics["new_bay_count"], 1)
        expected = (
            STABILITY_CANCEL_WEIGHT * 10
            + STABILITY_NEW_BAY_WEIGHT
            + STABILITY_BLOCK_REALLOCATION_WEIGHT * 10
        )
        self.assertEqual(metrics["stability_cost"], expected)
        self.assertNotEqual(metrics["cancellation_quantity"], metrics["stability_cost"])

    def test_shortage_cannot_offset_another_pairs_cancellation(self):
        self.data["group_attrs"]["H"] = {"pod": "Q", "size": 20, "height": "STD"}
        self.data["previous_reservation"] = {
            ("Y1", "V", "G"): 10,
            ("Y2", "W", "H"): 10,
        }
        self.data["remaining_demand"] = {("V", "G"): 10, ("W", "H"): 10}
        metrics = canonical_stability_metrics(
            self.data,
            {("Y2", "W", "H"): 0},
            {("W", "H", 0): 10},
        )
        self.assertEqual(metrics["pair_discretionary_cancel"][("V", "G")], 10)
        self.assertNotIn(("W", "H"), metrics["pair_discretionary_cancel"])
        self.assertEqual(metrics["discretionary_cancel"], 10)

    def test_same_pair_shortage_explains_its_cancellation(self):
        metrics = canonical_stability_metrics(
            self.data,
            {("Y1", "V", "G"): 7},
            {("V", "G", 0): 3},
        )
        self.assertEqual(metrics["cancellation_quantity"], 3)
        self.assertEqual(metrics["discretionary_cancel"], 0)

    def test_actual_inventory_is_support_but_not_cancellation_baseline(self):
        self.data["previous_reservation"] = {}
        self.data["actual_inventory"] = {("Y1", "V", "G"): 5}
        metrics = canonical_stability_metrics(
            self.data,
            {("Y1", "V", "G"): 5},
            {("V", "G", 0): 0},
        )
        self.assertEqual(metrics["new_bay_count"], 0)
        self.assertEqual(metrics["cancellation_quantity"], 0)


if __name__ == "__main__":
    unittest.main()

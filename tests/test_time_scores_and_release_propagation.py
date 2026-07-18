import unittest

from rolling_model import existing_blocks
from rolling_solver import (
    _allowed,
    _block_scores,
    _build_dependency_graph,
    _direct_impact_pairs,
    _impact_directions,
    _propagate_impact_pairs,
)


def base_snapshot(blocks, bays, bay_size, group_attrs):
    return {
        "blocks": blocks,
        "bays": bays,
        "bay_block": {bay: block for bay, block in zip(bays, blocks)},
        "bays_in_block": {block: [bay] for bay, block in zip(bays, blocks)},
        "bay_size": bay_size,
        "capacity": {bay: 20 for bay in bays},
        "heights": ("STD", "HIGH"),
        "group_attrs": group_attrs,
        "distance": {},
        "periods": [0, 1],
        "remaining_demand": {},
        "forecast_arrivals": {},
        "forecast_outbound": {},
        "actual_inventory": {},
        "previous_reservation": {},
        "previous_din": {},
        "locked_inventory": {},
        "locked_height": {},
        "locked_release_local": {},
        "ship_release_local": {},
        "new_ships": [],
        "execution_periods": 1,
    }


class TimeScoreAndReleasePropagationTest(unittest.TestCase):
    def test_early_capacity_dominates_empty_final_period(self):
        snapshot = base_snapshot(
            ["K1", "K2"],
            ["Y1", "Y2"],
            {"Y1": 20, "Y2": 20},
            {"G": {"pod": "P", "size": 20, "height": "STD"}},
        )
        snapshot["capacity"] = {"Y1": 10, "Y2": 10}
        snapshot["distance"] = {("V", "K1"): 1, ("V", "K2"): 1}
        snapshot["remaining_demand"] = {("V", "G"): 5}
        snapshot["forecast_arrivals"] = {("V", "G", 0): 5}
        snapshot["ship_release_local"] = {"V": 10}
        snapshot["locked_inventory"] = {("Y1", "OLD"): 10}
        snapshot["locked_height"] = {("Y1", "OLD"): "STD"}
        snapshot["locked_release_local"] = {("Y1", "OLD"): 1}
        scores = _block_scores(snapshot)
        self.assertGreater(scores["V", "G", "K2"]["score"], scores["V", "G", "K1"]["score"])
        self.assertEqual(scores["V", "G", "K1"]["minimum_arrival_period_capacity"], 0)

    def test_capacity_pressure_uses_overlapping_period_capacity(self):
        def pressure(arrival_period):
            snapshot = base_snapshot(
                ["K1"],
                ["Y1"],
                {"Y1": 20},
                {
                    "A": {"pod": "P1", "size": 20, "height": "STD"},
                    "B": {"pod": "P2", "size": 20, "height": "STD"},
                },
            )
            snapshot["capacity"] = {"Y1": 10}
            snapshot["distance"] = {("V1", "K1"): 1, ("V2", "K1"): 1}
            snapshot["remaining_demand"] = {("V1", "A"): 2, ("V2", "B"): 2}
            snapshot["forecast_arrivals"] = {
                ("V1", "A", arrival_period): 2,
                ("V2", "B", arrival_period): 2,
            }
            snapshot["previous_reservation"] = {
                ("Y1", "V1", "A"): 2,
                ("Y1", "V2", "B"): 2,
            }
            snapshot["ship_release_local"] = {"V1": 10, "V2": 10}
            snapshot["locked_inventory"] = {("Y1", "OLD"): 10}
            snapshot["locked_height"] = {("Y1", "OLD"): "STD"}
            snapshot["locked_release_local"] = {("Y1", "OLD"): 1}
            _graph, edges, _resource = _build_dependency_graph(
                snapshot, _block_scores(snapshot)
            )
            return edges[0]["capacity_pressure"]

        self.assertGreater(pressure(0), pressure(1))

    def test_disappeared_pair_propagates_release_opportunity(self):
        snapshot = base_snapshot(
            ["K1", "K2", "K3"],
            ["Y1", "Y2", "Y3"],
            {"Y1": 20, "Y2": 20, "Y3": 40},
            {
                "A": {"pod": "P1", "size": 20, "height": "STD"},
                "B": {"pod": "P2", "size": 20, "height": "STD"},
                "C": {"pod": "P3", "size": 40, "height": "STD"},
            },
        )
        for ship in ("V1", "V2", "V3"):
            for block in snapshot["blocks"]:
                snapshot["distance"][ship, block] = 1
        snapshot["previous_reservation"] = {
            ("Y1", "V1", "A"): 10,
            ("Y2", "V2", "B"): 10,
            ("Y3", "V3", "C"): 10,
        }
        snapshot["previous_din"] = {
            ("Y1", "V1", "A", 0): 5,
            ("Y1", "V1", "A", 1): 5,
        }
        snapshot["remaining_demand"] = {("V2", "B"): 10, ("V3", "C"): 10}
        snapshot["forecast_arrivals"] = {
            ("V2", "B", 0): 5,
            ("V2", "B", 1): 5,
            ("V3", "C", 0): 5,
            ("V3", "C", 1): 5,
        }
        snapshot["ship_release_local"] = {"V1": 10, "V2": 10, "V3": 10}
        direct, _reasons = _direct_impact_pairs(snapshot, .1)
        directions = _impact_directions(snapshot)
        scores = _block_scores(snapshot)
        graph, _edges, _resource = _build_dependency_graph(snapshot, scores)
        propagated = _propagate_impact_pairs(
            direct,
            graph,
            impact_direction=directions,
        )
        a, b, c = ("V1", "A"), ("V2", "B"), ("V3", "C")
        self.assertIn(a, direct)
        self.assertIn(b, propagated["propagated_pairs"])
        self.assertEqual(propagated["propagation_type"][b], "release_opportunity")
        self.assertNotIn(c, propagated["affected_pairs"])
        release_blocks = {b: existing_blocks(snapshot, *a)}
        allowed = _allowed(
            snapshot,
            0,
            direct,
            set(propagated["propagated_pairs"]),
            scores,
            release_opportunity_blocks=release_blocks,
        )
        self.assertIn("Y1", allowed[b])


if __name__ == "__main__":
    unittest.main()

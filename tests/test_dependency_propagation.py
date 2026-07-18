import unittest

from rolling_solver import _build_dependency_graph, _direct_impact_pairs, _propagate_impact_pairs


class DependencyPropagationTest(unittest.TestCase):
    def setUp(self):
        self.a = ("V1", "A")
        self.b = ("V2", "B")
        self.c = ("V3", "C")
        self.d = ("V4", "D")
        self.snapshot = {
            "previous_reservation": {
                ("b1", "V1", "A"): 10,
                ("b1", "V2", "B"): 10,
                ("b3", "V3", "C"): 10,
                ("b2", "V4", "D"): 10,
            },
            "remaining_demand": {self.a: 20, self.b: 10, self.c: 10, self.d: 10},
            "new_ships": [],
        }
        self.graph = {
            self.a: [(self.b, .9)],
            self.b: [(self.a, .9), (self.d, .8)],
            self.c: [],
            self.d: [(self.b, .8)],
        }

    def test_direct_pair_and_two_level_propagation(self):
        direct, reasons = _direct_impact_pairs(self.snapshot, .1)
        self.assertEqual(direct, {self.a})
        self.assertIn("relative_demand_change", reasons[self.a])
        result = _propagate_impact_pairs(direct, self.graph, max_depth=2)
        self.assertIn(self.b, result["propagated_pairs"])
        self.assertIn(self.d, result["propagated_pairs"])
        self.assertNotIn(self.c, result["affected_pairs"])
        self.assertEqual(result["propagation_depth"][self.b], 1)
        self.assertEqual(result["propagation_depth"][self.d], 2)

    def test_depth_one_excludes_secondary_neighbor(self):
        direct, _ = _direct_impact_pairs(self.snapshot, .1)
        result = _propagate_impact_pairs(direct, self.graph, max_depth=1)
        self.assertIn(self.b, result["propagated_pairs"])
        self.assertNotIn(self.d, result["affected_pairs"])

    def test_propagation_is_deterministic(self):
        direct, _ = _direct_impact_pairs(self.snapshot, .1)
        first = _propagate_impact_pairs(direct, self.graph, max_depth=2)
        second = _propagate_impact_pairs(direct, self.graph, max_depth=2)
        self.assertEqual(first, second)

    def test_resource_graph_respects_size_and_candidate_compatibility(self):
        pairs = [self.a, self.b, self.c, self.d]
        snapshot = {
            "blocks": ["k1", "k2", "k3"],
            "periods": [0, 1],
            "remaining_demand": {pair: 10 for pair in pairs},
            "group_attrs": {
                "A": {"size": 20, "height": 86},
                "B": {"size": 20, "height": 96},
                "C": {"size": 40, "height": 86},
                "D": {"size": 20, "height": 86},
            },
            "forecast_arrivals": {
                (ship, group, period): 5
                for ship, group in pairs
                for period in [0, 1]
            },
            "previous_reservation": {},
            "previous_din": {},
            "actual_inventory": {},
            "bay_block": {},
        }
        eligible = {
            self.a: {"k1"},
            self.b: {"k1", "k2"},
            self.c: {"k1"},
            self.d: {"k2"},
        }
        scores = {
            (ship, group, block): {
                "score": 1.0 if block in eligible[ship, group] else 0.0,
                "compatible_capacity": 20 if block in eligible[ship, group] else 0,
                "capacity_by_period": {
                    period: 20 if block in eligible[ship, group] else 0
                    for period in snapshot["periods"]
                },
            }
            for ship, group in pairs
            for block in snapshot["blocks"]
        }

        graph, edges, _ = _build_dependency_graph(snapshot, scores)
        neighbors = {pair: {neighbor for neighbor, _ in graph[pair]} for pair in pairs}
        self.assertIn(self.b, neighbors[self.a])
        self.assertIn(self.d, neighbors[self.b])
        self.assertNotIn(self.c, neighbors[self.a])
        self.assertNotIn(self.d, neighbors[self.a])
        self.assertEqual(edges, sorted(
            edges,
            key=lambda edge: (
                -edge["dependency_score"],
                tuple(edge["pair_a"]),
                tuple(edge["pair_b"]),
            ),
        ))


if __name__ == "__main__":
    unittest.main()

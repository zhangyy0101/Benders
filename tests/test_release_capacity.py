import unittest

from gurobipy import GRB

from rolling_model import build_rolling_model, extract_rolling_solution, ship_present_at
from rolling_solver import validate_rolling_solution


def release_snapshot():
    return {
        "blocks": ["K1"],
        "bays": ["Y1"],
        "bay_block": {"Y1": "K1"},
        "bays_in_block": {"K1": ["Y1"]},
        "bay_size": {"Y1": 20},
        "capacity": {"Y1": 5},
        "heights": ("STD", "HIGH"),
        "group_attrs": {
            "G_STD": {"pod": "P1", "size": 20, "height": "STD"},
            "G_HIGH": {"pod": "P2", "size": 20, "height": "HIGH"},
        },
        "distance": {("A", "K1"): 1, ("B", "K1"): 1},
        "periods": [0, 1, 2, 3],
        "remaining_demand": {("A", "G_STD"): 5, ("B", "G_HIGH"): 5},
        "forecast_arrivals": {("A", "G_STD", 0): 5, ("B", "G_HIGH", 2): 5},
        "forecast_outbound": {},
        "actual_inventory": {},
        "previous_reservation": {},
        "previous_din": {},
        "locked_inventory": {},
        "locked_height": {},
        "locked_release_local": {},
        "ship_release_local": {"A": 2, "B": 10},
        "active_ships": ["A", "B"],
        "new_ships": ["A", "B"],
        "continuing_ships": [],
        "period_hours": 6,
        "execution_periods": 4,
        "lookahead_periods": 4,
    }


class ReleaseCapacityTest(unittest.TestCase):
    def test_release_allows_capacity_and_height_reuse(self):
        data = release_snapshot()
        self.assertTrue(ship_present_at(data, "A", 1))
        self.assertFalse(ship_present_at(data, "A", 2))
        model, variables, expressions = build_rolling_model(data)
        model.Params.OutputFlag = 0
        model.optimize()
        self.assertEqual(model.Status, GRB.OPTIMAL)
        solution = extract_rolling_solution(variables, expressions)
        self.assertEqual(solution["components"]["predicted_shortage"], 0)
        self.assertAlmostEqual(solution["reservation"]["Y1", "A", "G_STD"], 5)
        self.assertAlmostEqual(solution["reservation"]["Y1", "B", "G_HIGH"], 5)
        self.assertAlmostEqual(solution["inventory"]["Y1", "A", "G_STD", 2], 0)
        report = validate_rolling_solution(data, solution)
        self.assertTrue(report["feasible"], report)
        self.assertEqual(report["violations"]["released_inventory"], 0)


if __name__ == "__main__":
    unittest.main()

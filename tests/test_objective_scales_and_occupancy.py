import unittest

from gurobipy import GRB

from rolling_data import _realized_space_metrics
from rolling_model import build_rolling_model, compute_objective_scales, extract_rolling_solution


def objective_snapshot():
    return {
        "blocks": ["K1", "K2"],
        "bays": ["Y1", "Y2"],
        "bay_block": {"Y1": "K1", "Y2": "K2"},
        "bays_in_block": {"K1": ["Y1"], "K2": ["Y2"]},
        "bay_size": {"Y1": 20, "Y2": 20},
        "capacity": {"Y1": 10, "Y2": 10},
        "heights": ("STD", "HIGH"),
        "group_attrs": {"G": {"pod": "P", "size": 20, "height": "STD"}},
        "distance": {("V", "K1"): 1, ("V", "K2"): 2},
        "periods": [0, 1],
        "remaining_demand": {("V", "G"): 5},
        "forecast_arrivals": {("V", "G", 0): 5},
        "forecast_outbound": {},
        "actual_inventory": {},
        "previous_reservation": {},
        "previous_din": {},
        "locked_inventory": {},
        "locked_height": {},
        "locked_release_local": {},
        "ship_release_local": {"V": 10},
        "active_ships": ["V"],
        "new_ships": ["V"],
        "continuing_ships": [],
        "period_hours": 6,
        "execution_periods": 1,
        "lookahead_periods": 2,
    }


def solve_fixed(snapshot, allowed):
    scales = compute_objective_scales(snapshot)
    model, variables, expressions = build_rolling_model(
        snapshot,
        allowed_bays=allowed,
        objective_scales=scales,
    )
    for key, variable in variables["reservation"].items():
        target = 5 if key == ("Y1", "V", "G") else 0
        variable.LB = target
        variable.UB = target
    for key, variable in variables["din"].items():
        target = 5 if key == ("Y1", "V", "G", 0) else 0
        variable.LB = target
        variable.UB = target
    model.Params.OutputFlag = 0
    model.optimize()
    if model.Status != GRB.OPTIMAL:
        raise AssertionError(f"fixed model status {model.Status}")
    return extract_rolling_solution(variables, expressions)["components"]


class ObjectiveScaleAndOccupancyTest(unittest.TestCase):
    def test_fixed_scales_make_stage_objectives_comparable(self):
        snapshot = objective_snapshot()
        local = solve_fixed(snapshot, {("V", "G"): ["Y1"]})
        global_result = solve_fixed(snapshot, None)
        for field in (
            "concentration_raw",
            "occupancy_balance_raw",
            "distance_raw",
            "in_out_conflict_raw",
            "concentration_normalized",
            "occupancy_balance_normalized",
            "distance_normalized",
            "in_out_conflict_normalized",
            "operations_cost",
        ):
            self.assertAlmostEqual(local[field], global_result[field], places=8, msg=field)
        self.assertEqual(local["concentration_scale"], 2)
        self.assertEqual(global_result["concentration_scale"], 2)

    def test_actual_support_prevents_mip_new_bay_charge(self):
        snapshot = objective_snapshot()
        snapshot["actual_inventory"] = {("Y1", "V", "G"): 2}
        model, variables, expressions = build_rolling_model(
            snapshot,
            allowed_bays={("V", "G"): ["Y1"]},
            objective_scales=compute_objective_scales(snapshot),
        )
        model.Params.OutputFlag = 0
        model.optimize()
        self.assertEqual(model.Status, GRB.OPTIMAL)
        components = extract_rolling_solution(variables, expressions)["components"]
        self.assertEqual(components["new_bay_count"], 0)

    def test_realized_balance_uses_utilization_not_absolute_quantity(self):
        case = {
            "blocks": ["K1", "K2"],
            "bays": ["Y1", "Y2"],
            "bays_in_block": {"K1": ["Y1"], "K2": ["Y2"]},
            "bay_block": {"Y1": "K1", "Y2": "K2"},
            "capacity": {"Y1": 10, "Y2": 20},
            "group_attrs": {"G": {"pod": "P", "size": 20, "height": "STD"}},
            "realized_ship_release_period": {"V": 10},
            "old_release_period": {},
        }
        state = {
            "actual_inventory": {("Y1", "V", "G"): 5, ("Y2", "V", "G"): 5},
            "locked_inventory": {},
        }
        metrics = _realized_space_metrics(case, state, 0)
        self.assertAlmostEqual(metrics["realized_peak_block_utilization"], .5)
        self.assertAlmostEqual(
            metrics["realized_mean_absolute_utilization_deviation"], .125
        )
        self.assertAlmostEqual(metrics["realized_max_utilization_spread"], .25)


if __name__ == "__main__":
    unittest.main()

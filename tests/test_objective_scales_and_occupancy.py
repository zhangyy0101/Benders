import unittest

from gurobipy import GRB

from config import (
    OPERATION_WEIGHT_PROFILE,
    OPERATION_WEIGHT_PROFILES,
    OPERATION_WEIGHT_BALANCE,
    OPERATION_WEIGHT_CONCENTRATION,
    OPERATION_WEIGHT_DISTANCE,
    OPERATION_WEIGHT_IN_OUT_CONFLICT,
)
from rolling_data import _realized_space_metrics
from rolling_model import (
    build_rolling_model,
    compute_objective_scales,
    extract_rolling_solution,
    resolve_operation_weights,
)


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


def solve_fixed(snapshot, allowed, *, operation_weights=None):
    scales = compute_objective_scales(snapshot)
    model, variables, expressions = build_rolling_model(
        snapshot,
        allowed_bays=allowed,
        objective_scales=scales,
        operation_weights=operation_weights,
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
            "normalized_operations_score",
        ):
            self.assertAlmostEqual(local[field], global_result[field], places=8, msg=field)
        self.assertEqual(local["concentration_scale"], 2)
        self.assertEqual(global_result["concentration_scale"], 2)
        self.assertEqual(local["occupancy_balance_scale"], 2)
        expected_score = (
            OPERATION_WEIGHT_CONCENTRATION * local["concentration_normalized"]
            + OPERATION_WEIGHT_BALANCE * local["occupancy_balance_normalized"]
            + OPERATION_WEIGHT_DISTANCE * local["distance_normalized"]
            + OPERATION_WEIGHT_IN_OUT_CONFLICT
            * local["in_out_conflict_normalized"]
        )
        self.assertAlmostEqual(
            local["normalized_operations_score"], expected_score, places=8
        )
        self.assertEqual(OPERATION_WEIGHT_PROFILE, "business")
        self.assertAlmostEqual(local["distance_weight"], .4)
        self.assertAlmostEqual(local["occupancy_balance_weight"], .3)
        self.assertAlmostEqual(local["concentration_weight"], .2)
        self.assertAlmostEqual(local["in_out_conflict_weight"], .1)
        self.assertAlmostEqual(
            local["normalized_operations_score"],
            local["concentration_weighted"]
            + local["occupancy_balance_weighted"]
            + local["distance_weighted"]
            + local["in_out_conflict_weighted"],
        )

    def test_scales_exclude_pairs_without_positive_reachable_flow(self):
        snapshot = objective_snapshot()
        baseline = compute_objective_scales(snapshot)
        snapshot["remaining_demand"]["W", "G"] = 7
        snapshot["active_ships"].append("W")
        snapshot["ship_release_local"]["W"] = 10
        snapshot["distance"]["W", "K1"] = 100
        snapshot["distance"]["W", "K2"] = 200
        self.assertEqual(compute_objective_scales(snapshot), baseline)

    def test_balance_uses_tight_universal_deviation_bound(self):
        snapshot = objective_snapshot()
        snapshot["blocks"].append("K3")
        snapshot["bays"].append("Y3")
        snapshot["bay_block"]["Y3"] = "K3"
        snapshot["bays_in_block"]["K3"] = ["Y3"]
        snapshot["bay_size"]["Y3"] = 20
        snapshot["capacity"]["Y3"] = 10
        snapshot["distance"]["V", "K3"] = 3
        scales = compute_objective_scales(snapshot)
        self.assertAlmostEqual(scales["occupancy_balance_scale"], 8 / 3)
        self.assertEqual(scales["concentration_scale"], 3)
        self.assertEqual(scales["distance_scale"], 15)

    def test_scales_reject_invalid_physical_coefficients(self):
        snapshot = objective_snapshot()
        snapshot["distance"]["V", "K1"] = -1
        with self.assertRaisesRegex(ValueError, "transport distances"):
            compute_objective_scales(snapshot)

        snapshot = objective_snapshot()
        snapshot["forecast_outbound"]["K1", 0] = -1
        with self.assertRaisesRegex(ValueError, "outbound quantities"):
            compute_objective_scales(snapshot)

    def test_explicit_sensitivity_profile_changes_only_weighted_score(self):
        snapshot = objective_snapshot()
        business = solve_fixed(snapshot, None)
        equal = solve_fixed(
            snapshot,
            None,
            operation_weights=OPERATION_WEIGHT_PROFILES[
                "equal_weight_ablation"
            ],
        )
        for field in (
            "concentration_raw",
            "occupancy_balance_raw",
            "distance_raw",
            "in_out_conflict_raw",
            "concentration_normalized",
            "occupancy_balance_normalized",
            "distance_normalized",
            "in_out_conflict_normalized",
        ):
            self.assertAlmostEqual(business[field], equal[field], msg=field)
        self.assertNotAlmostEqual(
            business["normalized_operations_score"],
            equal["normalized_operations_score"],
        )

    def test_operation_weight_validation_rejects_incomplete_profiles(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            resolve_operation_weights({})
        with self.assertRaisesRegex(ValueError, "at least one"):
            resolve_operation_weights({
                "concentration": 0,
                "balance": 0,
                "distance": 0,
                "in_out_conflict": 0,
            })

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

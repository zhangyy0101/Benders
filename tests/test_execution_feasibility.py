import unittest

from rolling_data import (
    advance_state,
    build_synthetic_rolling_case,
    initial_simulation_state,
    validate_execution_state,
)


class ExecutionFeasibilityTest(unittest.TestCase):
    def setUp(self):
        self.case = build_synthetic_rolling_case(
            seed=21,
            num_blocks=2,
            bays_per_block=4,
            num_ships=1,
            cycles=1,
            bay_capacity=10,
            initial_utilization=0,
            forecast_error=0,
            containers_per_ship_range=(20, 20),
        )
        self.ship = self.case["ships"][0]
        self.group = next(group for ship, group in self.case["true_total"] if ship == self.ship)
        self.case["true_flow"] = {(self.ship, self.group, 0): 5}
        self.case["planned_ship_release_period"][self.ship] = 10
        self.case["realized_ship_release_period"][self.ship] = 10

    def compatible_bays(self):
        attrs = self.case["group_attrs"][self.group]
        return [
            bay for bay in self.case["bays"]
            if self.case["bay_size"][bay] == attrs["size"]
        ]

    def test_infeasible_plan_moves_to_feasible_fallback(self):
        planned_bay, fallback_bay = self.compatible_bays()[:2]
        state = initial_simulation_state(self.case)
        self.case["realized_ship_release_period"]["X"] = 10
        state["actual_inventory"] = {(planned_bay, "X", self.group): 10}
        solution = {
            "reservation": {
                (planned_bay, self.ship, self.group): 5,
                (fallback_bay, self.ship, self.group): 5,
            },
            "din": {(planned_bay, self.ship, self.group, 0): 5},
        }
        next_state, metrics = advance_state(self.case, state, solution)
        self.assertEqual(metrics["planned_placement_quantity"], 0)
        self.assertEqual(metrics["planned_infeasible_quantity"], 5)
        self.assertEqual(metrics["fallback_placement_quantity"], 5)
        self.assertEqual(metrics["realized_unplaced"], 0)
        self.assertEqual(
            next_state["actual_inventory"][fallback_bay, self.ship, self.group], 5
        )
        report = validate_execution_state(self.case, next_state, 4)
        self.assertTrue(report["feasible"], report)

    def test_size_and_height_infeasibility_becomes_unplaced(self):
        compatible = self.compatible_bays()
        fallback_bay = compatible[0]
        wrong_size_bay = next(
            bay for bay in self.case["bays"]
            if self.case["bay_size"][bay] != self.case["group_attrs"][self.group]["size"]
        )
        attrs = self.case["group_attrs"][self.group]
        opposite_height_group = next(
            group for group, values in self.case["group_attrs"].items()
            if values["size"] == attrs["size"] and values["height"] != attrs["height"]
        )
        state = initial_simulation_state(self.case)
        self.case["realized_ship_release_period"]["X"] = 10
        state["actual_inventory"] = {(fallback_bay, "X", opposite_height_group): 1}
        solution = {
            "reservation": {
                (wrong_size_bay, self.ship, self.group): 5,
                (fallback_bay, self.ship, self.group): 5,
            },
            "din": {(wrong_size_bay, self.ship, self.group, 0): 5},
        }
        next_state, metrics = advance_state(self.case, state, solution)
        self.assertEqual(metrics["planned_placement_quantity"], 0)
        self.assertEqual(metrics["fallback_placement_quantity"], 0)
        self.assertEqual(metrics["planned_infeasible_quantity"], 5)
        self.assertEqual(metrics["realized_unplaced"], 5)
        self.assertEqual(
            metrics["planned_placement_quantity"]
            + metrics["fallback_placement_quantity"]
            + metrics["realized_unplaced"],
            metrics["realized_arrivals"],
        )
        report = validate_execution_state(self.case, next_state, 4)
        self.assertTrue(report["feasible"], report)


if __name__ == "__main__":
    unittest.main()

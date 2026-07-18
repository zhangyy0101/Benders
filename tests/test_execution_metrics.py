import unittest

from rolling_data import advance_state, build_synthetic_rolling_case, initial_simulation_state


def exact_execution_solution(case, state):
    now = state["cycle"] * case["execution_periods"]
    reservation, din = {}, {}
    for (j, g, absolute), q in case["true_flow"].items():
        if not (now <= absolute < now + case["execution_periods"]):
            continue
        bay = next(i for i in case["bays"] if case["bay_size"][i] == case["group_attrs"][g]["size"])
        reservation[bay, j, g] = reservation.get((bay, j, g), 0) + q
        din[bay, j, g, absolute - now] = q
    return {"reservation": reservation, "din": din}


class ExecutionMetricsTest(unittest.TestCase):
    def test_non_overlapping_execution_windows(self):
        case = build_synthetic_rolling_case(
            seed=3, num_blocks=2, bays_per_block=4, num_ships=1, cycles=2,
            bay_capacity=100, initial_utilization=0, forecast_error=0,
        )
        state = initial_simulation_state(case)
        first_solution = exact_execution_solution(case, state)
        expected_first_distance = sum(
            q * case["distance"][ship, case["bay_block"][bay]]
            for (bay, ship, _group, _period), q in first_solution["din"].items()
        )
        state, first = advance_state(case, state, first_solution)
        second_solution = exact_execution_solution(case, state)
        state, second = advance_state(case, state, second_solution)
        expected_first = sum(q for (_j, _g, t), q in case["true_flow"].items() if 0 <= t < 4)
        expected_second = sum(q for (_j, _g, t), q in case["true_flow"].items() if 4 <= t < 8)
        self.assertEqual(first["realized_arrivals"], expected_first)
        self.assertEqual(second["realized_arrivals"], expected_second)
        for metrics in (first, second):
            self.assertEqual(
                metrics["planned_placement_quantity"]
                + metrics["fallback_placement_quantity"]
                + metrics["realized_unplaced"],
                metrics["realized_arrivals"],
            )
        self.assertEqual(first["fallback_placement_quantity"], 0)
        self.assertEqual(first["realized_unplaced"], 0)
        self.assertEqual(first["realized_distance"], expected_first_distance)
        self.assertEqual(
            state["unplaced_actual"], first["realized_unplaced"] + second["realized_unplaced"]
        )

    def test_predicted_shortage_does_not_create_realized_unplaced(self):
        case = build_synthetic_rolling_case(
            seed=4, num_blocks=2, bays_per_block=4, num_ships=1, cycles=1,
            bay_capacity=100, initial_utilization=0, forecast_error=0,
        )
        state = initial_simulation_state(case)
        solution = exact_execution_solution(case, state)
        solution["shortage"] = {("fake", "fake", 0): 999}
        _state, metrics = advance_state(case, state, solution)
        self.assertEqual(metrics["realized_unplaced"], 0)


if __name__ == "__main__":
    unittest.main()

import unittest

from rolling_data import build_synthetic_rolling_case, initial_simulation_state, optimization_snapshot


class InformationBoundaryTest(unittest.TestCase):
    def test_hidden_truth_does_not_determine_planned_release(self):
        case = build_synthetic_rolling_case(
            seed=9,
            num_blocks=2,
            bays_per_block=4,
            num_ships=2,
            cycles=2,
            containers_per_ship_range=(40, 60),
        )
        planned = dict(case["planned_ship_release_period"])
        case["true_total"] = {key: value * 10 for key, value in case["true_total"].items()}
        case["true_flow"] = {key: value * 10 for key, value in case["true_flow"].items()}
        self.assertEqual(case["planned_ship_release_period"], planned)
        self.assertEqual(case["release_period_basis"], "external_schedule")

    def test_optimizer_snapshot_excludes_hidden_realization(self):
        case = build_synthetic_rolling_case(
            seed=10,
            num_blocks=2,
            bays_per_block=4,
            num_ships=1,
            cycles=1,
            containers_per_ship_range=(40, 40),
        )
        snapshot = optimization_snapshot(case, initial_simulation_state(case))
        for forbidden in (
            "true_total",
            "true_flow",
            "realized_ship_release_period",
            "forecast_mae_by_cycle",
            "forecast_mape_by_cycle",
            "forecast_total_error_by_cycle",
            "forecast_timing_error_by_cycle",
        ):
            self.assertNotIn(forbidden, snapshot)
        serialized_keys = set()

        def collect_keys(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    serialized_keys.add(str(key))
                    collect_keys(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    collect_keys(item)

        collect_keys(snapshot)
        for forbidden in ("true_flow", "true_total", "realized_ship_release"):
            self.assertFalse(any(forbidden in key for key in serialized_keys))
        ship = case["ships"][0]
        self.assertEqual(
            snapshot["ship_release_local"][ship],
            case["planned_ship_release_period"][ship],
        )

    def test_release_delay_is_hidden_from_optimizer(self):
        case = build_synthetic_rolling_case(
            seed=11,
            num_blocks=2,
            bays_per_block=4,
            num_ships=1,
            cycles=1,
            release_delay_periods=2,
            containers_per_ship_range=(40, 40),
        )
        ship = case["ships"][0]
        self.assertEqual(
            case["realized_ship_release_period"][ship],
            case["planned_ship_release_period"][ship] + 2,
        )
        snapshot = optimization_snapshot(case, initial_simulation_state(case))
        self.assertEqual(
            snapshot["ship_release_local"][ship],
            case["planned_ship_release_period"][ship],
        )

    def test_outbound_forecast_does_not_require_hidden_outbound_truth(self):
        case = build_synthetic_rolling_case(
            seed=12,
            num_blocks=2,
            bays_per_block=4,
            num_ships=1,
            cycles=4,
            initial_utilization=0,
            containers_per_ship_range=(40, 40),
        )
        ship = case["ships"][0]
        group = next(iter(case["group_attrs"]))
        case["eta_period"][ship] = 10
        case["planned_ship_release_period"][ship] = 14
        state = initial_simulation_state(case)
        state["cycle"] = 3
        state["actual_inventory"] = {(case["bays"][0], ship, group): 40}
        for hidden in (
            "true_flow",
            "true_total",
            "ship_outbound_flow",
            "realized_ship_release_period",
        ):
            del case[hidden]

        snapshot = optimization_snapshot(case, state)

        self.assertIn(ship, snapshot["outbound_relevant_ships"])
        self.assertGreater(sum(snapshot["forecast_outbound"].values()), 0)


if __name__ == "__main__":
    unittest.main()

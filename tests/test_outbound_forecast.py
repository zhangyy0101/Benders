import unittest

from rolling_data import (
    build_synthetic_rolling_case,
    build_visible_ship_outbound_forecast,
    initial_simulation_state,
    optimization_snapshot,
    visible_ship_block_basis,
)


class OutboundForecastTest(unittest.TestCase):
    @staticmethod
    def profile_case(eta=10, release=14):
        return {
            "execution_periods": 4,
            "eta_period": {"V": eta},
            "planned_ship_release_period": {"V": release},
            "forecasts": {},
        }

    @staticmethod
    def profile_state(total=100):
        return {"actual_inventory": {("Y", "V", "G"): total}}

    def test_loading_phase_profile_is_truncated_after_full_distribution(self):
        outbound = build_visible_ship_outbound_forecast(
            self.profile_case(),
            self.profile_state(),
            3,
            "V",
        )
        self.assertEqual(outbound, {12: 25, 13: 25})
        self.assertEqual(sum(outbound.values()), 50)

    def test_pre_eta_ship_keeps_complete_profile(self):
        outbound = build_visible_ship_outbound_forecast(
            self.profile_case(),
            self.profile_state(),
            2,
            "V",
        )
        self.assertEqual(outbound, {10: 25, 11: 25, 12: 25, 13: 25})
        self.assertEqual(sum(outbound.values()), 100)

    def test_released_ship_has_no_remaining_profile(self):
        outbound = build_visible_ship_outbound_forecast(
            self.profile_case(),
            self.profile_state(),
            4,
            "V",
        )
        self.assertEqual(outbound, {})

    def test_horizon_truncation_does_not_redistribute_quantity(self):
        outbound = build_visible_ship_outbound_forecast(
            self.profile_case(release=16),
            self.profile_state(),
            2,
            "V",
            horizon_end=13,
        )
        self.assertEqual(set(outbound), {10, 11, 12})
        self.assertEqual(list(outbound.values()), [17, 17, 17])
        self.assertEqual(sum(outbound.values()), 51)

    def test_loading_phase_ship_enters_snapshot_outbound(self):
        case = build_synthetic_rolling_case(
            seed=2,
            num_blocks=2,
            bays_per_block=2,
            num_ships=1,
            cycles=4,
            initial_utilization=0,
            forecast_error=0,
            containers_per_ship_range=(40, 40),
        )
        ship = case["ships"][0]
        group = next(
            group
            for group, attrs in case["group_attrs"].items()
            if attrs["size"] == case["bay_size"][case["bays"][0]]
        )
        case["eta_period"][ship] = 10
        case["planned_ship_release_period"][ship] = 14
        case["forecasts"] = {}
        state = initial_simulation_state(case)
        state["cycle"] = 3
        state["actual_inventory"] = {(case["bays"][0], ship, group): 40}

        snapshot = optimization_snapshot(case, state)

        self.assertNotIn(ship, snapshot["active_ships"])
        self.assertIn(ship, snapshot["outbound_relevant_ships"])
        self.assertIn(
            ship,
            snapshot["outbound_forecast_diagnostics"]["loading_phase_ships"],
        )
        self.assertGreater(sum(snapshot["forecast_outbound"].values()), 0)

    def test_released_ship_is_not_outbound_relevant(self):
        case = build_synthetic_rolling_case(
            seed=3,
            num_blocks=2,
            bays_per_block=2,
            num_ships=1,
            cycles=4,
            initial_utilization=0,
        )
        ship = case["ships"][0]
        case["eta_period"][ship] = 8
        case["planned_ship_release_period"][ship] = 12
        state = initial_simulation_state(case)
        state["cycle"] = 3
        snapshot = optimization_snapshot(case, state)
        self.assertNotIn(ship, snapshot["outbound_relevant_ships"])

    def test_block_basis_combines_actual_and_unexecuted_reservation(self):
        case = {
            "blocks": ["B1", "B2"],
            "bay_block": {"Y1": "B1", "Y2": "B2"},
        }
        state = {"actual_inventory": {("Y1", "V", "G"): 30}}
        previous = {("Y2", "V", "G"): 20, ("Y1", "W", "G"): 99}
        self.assertEqual(
            visible_ship_block_basis(case, state, previous, "V"),
            {"B1": 30, "B2": 20},
        )


if __name__ == "__main__":
    unittest.main()

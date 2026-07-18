import unittest

from rolling_data import (
    build_synthetic_rolling_case,
    build_visible_ship_outbound_forecast,
    initial_simulation_state,
    summarize_period_space_metrics,
)


class PilotDataGenerationTest(unittest.TestCase):
    def test_requested_initial_utilizations_are_realized(self):
        for utilization in (.25, .40, .55, .70, .80):
            case = build_synthetic_rolling_case(
                seed=4,
                num_blocks=4,
                bays_per_block=5,
                num_ships=3,
                cycles=3,
                initial_utilization=utilization,
            )
            tolerance = 1 / case["initial_total_capacity"]
            self.assertLessEqual(
                abs(case["realized_initial_utilization"] - utilization),
                tolerance,
            )
            self.assertEqual(case["initialization_shortfall"], 0)
            by_bay = {}
            heights = {}
            for (bay, old_ship), quantity in case["locked_initial"].items():
                by_bay[bay] = by_bay.get(bay, 0) + quantity
                heights.setdefault(bay, set()).add(
                    case["locked_height_initial"][bay, old_ship]
                )
            for bay, quantity in by_bay.items():
                self.assertLessEqual(quantity, case["capacity"][bay])
                self.assertEqual(len(heights[bay]), 1)

    def test_initial_distribution_is_seeded_and_heterogeneous(self):
        kwargs = dict(
            num_blocks=4,
            bays_per_block=5,
            num_ships=3,
            cycles=3,
            initial_utilization=.70,
        )
        first = build_synthetic_rolling_case(seed=1, **kwargs)
        repeat = build_synthetic_rolling_case(seed=1, **kwargs)
        other = build_synthetic_rolling_case(seed=2, **kwargs)
        self.assertEqual(first["locked_initial"], repeat["locked_initial"])
        self.assertEqual(first["locked_height_initial"], repeat["locked_height_initial"])
        self.assertNotEqual(first["locked_initial"], other["locked_initial"])
        self.assertGreater(len(set(first["locked_initial"].values())), 1)

    def test_forecast_trajectory_converges_on_average(self):
        modes = (
            "multiplicative",
            "timing_shift",
            "booking_add_cancel",
            "ship_correlated",
            "mixed",
        )
        for mode in modes:
            early = []
            late = []
            for seed in range(6):
                case = build_synthetic_rolling_case(
                    seed=seed,
                    num_blocks=4,
                    bays_per_block=6,
                    num_ships=8,
                    cycles=6,
                    active_ship_overlap=2,
                    forecast_error=.20,
                    forecast_error_mode=mode,
                )
                early.append(case["forecast_mae_by_cycle"][0])
                late.append(case["forecast_mae_by_cycle"][3])
            self.assertLess(sum(late) / len(late), sum(early) / len(early), mode)

    def test_timing_and_booking_information_stabilize_over_cycles(self):
        for mode, diagnostic in (
            ("timing_shift", "forecast_timing_error_by_cycle"),
            ("booking_add_cancel", "forecast_total_error_by_cycle"),
        ):
            early = []
            late = []
            for seed in range(8):
                case = build_synthetic_rolling_case(
                    seed=seed,
                    num_blocks=4,
                    bays_per_block=6,
                    num_ships=8,
                    cycles=6,
                    active_ship_overlap=2,
                    forecast_error=.20,
                    forecast_error_mode=mode,
                )
                early.append(case[diagnostic][0])
                late.append(case[diagnostic][3])
            self.assertLessEqual(
                sum(late) / len(late),
                sum(early) / len(early),
                mode,
            )

    def test_continuing_ship_outbound_uses_actual_plus_remaining_forecast(self):
        case = build_synthetic_rolling_case(
            seed=0,
            num_blocks=2,
            bays_per_block=2,
            num_ships=1,
            cycles=3,
            initial_utilization=0,
            forecast_error=0,
        )
        ship = case["ships"][0]
        group = next(iter(case["group_attrs"]))
        cycle = 1
        now = cycle * case["execution_periods"]
        case["forecasts"] = {(cycle, ship, group, now + 1): 60}
        state = initial_simulation_state(case)
        state["cycle"] = cycle
        state["actual_inventory"] = {(case["bays"][0], ship, group): 40}
        outbound = build_visible_ship_outbound_forecast(case, state, cycle, ship)
        self.assertEqual(sum(outbound.values()), 100)

        case["forecasts"] = {(cycle, ship, group, now + 1): 50}
        state["actual_inventory"] = {(case["bays"][0], ship, group): 50}
        self.assertEqual(
            sum(build_visible_ship_outbound_forecast(case, state, cycle, ship).values()),
            100,
        )

    def test_nominal_outbound_rate_shortens_public_duration(self):
        common = dict(
            seed=3,
            num_blocks=3,
            bays_per_block=3,
            num_ships=2,
            cycles=2,
            containers_per_ship_range=(600, 600),
        )
        slow = build_synthetic_rolling_case(
            nominal_outbound_rate_per_ship_period=50,
            **common,
        )
        fast = build_synthetic_rolling_case(
            nominal_outbound_rate_per_ship_period=300,
            **common,
        )
        for ship in slow["ships"]:
            self.assertGreaterEqual(
                slow["ship_operation_duration_periods"][ship],
                fast["ship_operation_duration_periods"][ship],
            )
        for old_ship in slow["old_release_period"]:
            self.assertGreaterEqual(
                slow["old_release_period"][old_ship],
                fast["old_release_period"][old_ship],
            )

    def test_period_space_summary_tracks_peak_activation_and_weighting(self):
        appeared = {("V", "P", "Y1"), ("V", "P", "Y2")}
        spaces = [
            {
                "support": appeared,
                "realized_peak_block_utilization": .9,
                "realized_mean_absolute_utilization_deviation": .2,
                "realized_max_utilization_spread": .4,
                "realized_ship_pod_bay_count_sum": 2,
                "realized_ship_pod_observation_count": 1,
                "realized_max_bays_per_ship_pod": 2,
            },
            {
                "support": set(),
                "realized_peak_block_utilization": .4,
                "realized_mean_absolute_utilization_deviation": .1,
                "realized_max_utilization_spread": .2,
                "realized_ship_pod_bay_count_sum": 0,
                "realized_ship_pod_observation_count": 0,
                "realized_max_bays_per_ship_pod": 0,
            },
        ]
        summary = summarize_period_space_metrics(spaces, set())
        self.assertEqual(summary["realized_peak_block_utilization"], .9)
        self.assertEqual(summary["realized_support_activation_count"], 2)
        self.assertEqual(summary["realized_average_bays_per_ship_pod"], 2)


if __name__ == "__main__":
    unittest.main()

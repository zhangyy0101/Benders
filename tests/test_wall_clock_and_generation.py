import unittest

from config import FORECAST_ERROR_MODES, WALL_TIME_TOLERANCE_SECONDS
from rolling_data import build_synthetic_rolling_case, initial_simulation_state, optimization_snapshot
from rolling_solver import postprocessing_reserve_seconds, solve_rolling_snapshot


class WallClockAndGenerationTest(unittest.TestCase):
    def test_postprocessing_reserve_is_scaled_and_bounded(self):
        self.assertEqual(postprocessing_reserve_seconds(0), 0)
        self.assertAlmostEqual(postprocessing_reserve_seconds(.05), .025)
        self.assertAlmostEqual(postprocessing_reserve_seconds(5), .75)
        self.assertAlmostEqual(postprocessing_reserve_seconds(10), 1.5)
        self.assertAlmostEqual(postprocessing_reserve_seconds(30), 4.5)
        self.assertAlmostEqual(postprocessing_reserve_seconds(60), 9.0)
        self.assertAlmostEqual(postprocessing_reserve_seconds(100), 10.0)

    def test_all_forecast_modes_are_reproducible(self):
        for mode in FORECAST_ERROR_MODES:
            first = build_synthetic_rolling_case(
                seed=31,
                num_blocks=2,
                bays_per_block=4,
                num_ships=2,
                cycles=2,
                forecast_error=.2,
                forecast_error_mode=mode,
                containers_per_ship_range=(30, 40),
            )
            second = build_synthetic_rolling_case(
                seed=31,
                num_blocks=2,
                bays_per_block=4,
                num_ships=2,
                cycles=2,
                forecast_error=.2,
                forecast_error_mode=mode,
                containers_per_ship_range=(30, 40),
            )
            self.assertEqual(first["forecasts"], second["forecasts"], mode)
            self.assertEqual(first["true_flow"], second["true_flow"], mode)

    def test_wall_clock_limit_includes_preprocessing_and_build(self):
        case = build_synthetic_rolling_case(
            seed=32,
            num_blocks=2,
            bays_per_block=4,
            num_ships=1,
            cycles=1,
            containers_per_ship_range=(30, 30),
        )
        snapshot = optimization_snapshot(case, initial_simulation_state(case))
        limit = .05
        result = solve_rolling_snapshot(
            snapshot,
            time_limit=limit,
            threads=1,
            seed=0,
            configuration="full",
        )
        self.assertLessEqual(
            result["total_wall_time"],
            limit + WALL_TIME_TOLERANCE_SECONDS,
        )
        self.assertIn("block_score_time", result)
        self.assertIn("model_build_time", result)
        self.assertIn("solver_time", result)


if __name__ == "__main__":
    unittest.main()

import unittest

from config import FORECAST_ERROR_MODES, WALL_TIME_TOLERANCE_SECONDS
from rolling_data import build_synthetic_rolling_case, initial_simulation_state, optimization_snapshot
from rolling_solver import (
    postprocessing_reserve_seconds,
    solve_rolling_snapshot,
    solver_return_guard_seconds,
)


class WallClockAndGenerationTest(unittest.TestCase):
    def test_postprocessing_reserve_is_scaled_and_bounded(self):
        self.assertEqual(postprocessing_reserve_seconds(0), 0)
        self.assertAlmostEqual(postprocessing_reserve_seconds(.05), .025)
        self.assertAlmostEqual(postprocessing_reserve_seconds(5), .5)
        self.assertAlmostEqual(postprocessing_reserve_seconds(10), .7)
        self.assertAlmostEqual(postprocessing_reserve_seconds(30), 2.1)
        self.assertAlmostEqual(postprocessing_reserve_seconds(60), 4.2)
        self.assertAlmostEqual(postprocessing_reserve_seconds(100), 7.0)
        self.assertAlmostEqual(postprocessing_reserve_seconds(120), 8.4)

    def test_solver_return_guard_is_scaled_and_bounded(self):
        self.assertEqual(solver_return_guard_seconds(0, 10), .25)
        self.assertAlmostEqual(solver_return_guard_seconds(20, 10), 2 / 3)
        self.assertAlmostEqual(solver_return_guard_seconds(60, 50), 2)
        self.assertAlmostEqual(solver_return_guard_seconds(120, 100), 4)
        self.assertAlmostEqual(solver_return_guard_seconds(180, 100), 6)
        self.assertAlmostEqual(solver_return_guard_seconds(60, 2), 1.99)

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
            result["online_decision_time"],
            limit + WALL_TIME_TOLERANCE_SECONDS,
        )
        self.assertGreaterEqual(
            result["audit_wall_time"],
            result["online_decision_time"],
        )
        self.assertIn(
            result["termination_status"],
            {"FEASIBLE", "TIME_LIMIT_FEASIBLE", "DEADLINE_MISS"},
        )
        if result["ok"]:
            self.assertNotEqual(
                result["termination_status"],
                "DEADLINE_MISS",
            )
        self.assertIn("block_score_time", result)
        self.assertIn("model_build_time", result)
        self.assertIn("solver_time", result)
        self.assertIn("solution_extract_time", result)
        self.assertIn("model_dispose_time", result)
        self.assertIn("validation_time", result)
        for stage in result["stages"]:
            self.assertIn("solver_return_guard", stage)
            self.assertIn("solver_return_overrun", stage)


if __name__ == "__main__":
    unittest.main()

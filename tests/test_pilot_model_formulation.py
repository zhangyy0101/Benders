import unittest
from types import SimpleNamespace

from gurobipy import GRB

from rolling_model import (
    build_rolling_model,
    compute_objective_scales,
    extract_rolling_solution,
    validate_snapshot_temporal_consistency,
)
from rolling_solver import (
    _block_scores,
    _horizon_end_block_utilization,
    baseline_residual_capacity_by_bay_period,
    canonical_stability_metrics,
    physical_residual_capacity_by_bay_period,
    solve_rolling_snapshot,
)
from test_objective_scales_and_occupancy import objective_snapshot
from test_time_scores_and_release_propagation import base_snapshot


class PilotModelFormulationTest(unittest.TestCase):
    def test_unknown_dependency_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dependency_profile"):
            solve_rolling_snapshot(
                objective_snapshot(),
                time_limit=1,
                dependency_profile="unknown",
            )

    def test_integer_solution_values_are_normalized_before_validation(self):
        variables = {
            "integer": {"i": SimpleNamespace(X=2.0000087, VType=GRB.INTEGER)},
            "binary": {"b": SimpleNamespace(X=.9999965, VType=GRB.BINARY)},
            "continuous": {"c": SimpleNamespace(X=2.0000087, VType=GRB.CONTINUOUS)},
        }
        solution = extract_rolling_solution(variables, {})
        self.assertEqual(solution["integer"]["i"], 2)
        self.assertEqual(solution["binary"]["b"], 1)
        self.assertAlmostEqual(solution["continuous"]["c"], 2.0000087)

    def test_release_after_arrival_is_rejected_and_cannot_create_flow(self):
        snapshot = objective_snapshot()
        snapshot["ship_release_local"]["V"] = 0
        with self.assertRaises(ValueError):
            validate_snapshot_temporal_consistency(snapshot)

        model, variables, expressions = build_rolling_model(snapshot)
        model.Params.OutputFlag = 0
        model.optimize()
        self.assertEqual(model.Status, GRB.OPTIMAL)
        self.assertFalse(variables["din"])
        solution = extract_rolling_solution(variables, expressions)
        self.assertEqual(solution["shortage"]["V", "G", 0], 5)

    def test_epigraph_and_exact_stability_match_with_fewer_binaries(self):
        snapshot = objective_snapshot()
        snapshot["previous_reservation"] = {("Y1", "V", "G"): 5}
        snapshot["previous_din"] = {("Y1", "V", "G", 0): 5}
        outcomes = {}
        model_sizes = {}
        for exact in (False, True):
            model, variables, expressions = build_rolling_model(
                snapshot,
                objective_scales=compute_objective_scales(snapshot),
                use_exact_stability_big_m=exact,
            )
            model.Params.OutputFlag = 0
            model.optimize()
            self.assertEqual(model.Status, GRB.OPTIMAL)
            solution = extract_rolling_solution(variables, expressions)
            canonical = canonical_stability_metrics(
                snapshot,
                solution["reservation"],
                solution["shortage"],
            )
            outcomes[exact] = (solution, canonical)
            model_sizes[exact] = (model.NumBinVars, model.NumVars, model.NumConstrs)

        epigraph, exact = outcomes[False], outcomes[True]
        self.assertEqual(epigraph[0]["reservation"], exact[0]["reservation"])
        self.assertAlmostEqual(
            epigraph[0]["components"]["predicted_shortage"],
            0,
            places=7,
        )
        for field in (
            "cancellation_quantity",
            "discretionary_cancel",
            "block_reallocation_quantity",
            "stability_cost",
        ):
            self.assertAlmostEqual(epigraph[1][field], exact[1][field], places=7)
        self.assertAlmostEqual(
            epigraph[0]["components"]["operations_cost"],
            exact[0]["components"]["operations_cost"],
            places=7,
        )
        self.assertLess(model_sizes[False][0], model_sizes[True][0])

    def test_frozen_commitment_changes_candidate_ranking(self):
        snapshot = base_snapshot(
            ["K1", "K2"],
            ["Y1", "Y2"],
            {"Y1": 20, "Y2": 20},
            {
                "NEW": {"pod": "P1", "size": 20, "height": "STD"},
                "OLD": {"pod": "P2", "size": 20, "height": "STD"},
            },
        )
        snapshot["capacity"] = {"Y1": 100, "Y2": 50}
        snapshot["distance"] = {
            ("VN", "K1"): 1,
            ("VN", "K2"): 1,
            ("VO", "K1"): 1,
            ("VO", "K2"): 1,
        }
        snapshot["remaining_demand"] = {("VN", "NEW"): 40, ("VO", "OLD"): 90}
        snapshot["forecast_arrivals"] = {
            ("VN", "NEW", 0): 40,
            ("VO", "OLD", 0): 90,
        }
        snapshot["previous_reservation"] = {("Y1", "VO", "OLD"): 90}
        snapshot["ship_release_local"] = {"VN": 10, "VO": 10}
        physical = physical_residual_capacity_by_bay_period(snapshot)
        physical_scores = _block_scores(snapshot, physical)
        baseline = baseline_residual_capacity_by_bay_period(
            snapshot,
            {("VO", "OLD")},
            physical,
        )
        baseline_scores = _block_scores(
            snapshot,
            baseline,
            capacity_basis="frozen_plan_baseline",
        )
        self.assertGreater(
            physical_scores["VN", "NEW", "K1"]["compatible_capacity"],
            physical_scores["VN", "NEW", "K2"]["compatible_capacity"],
        )
        self.assertGreater(
            baseline_scores["VN", "NEW", "K2"]["score"],
            baseline_scores["VN", "NEW", "K1"]["score"],
        )

    def test_quality_polish_uses_capacity_normalized_utilization(self):
        snapshot = objective_snapshot()
        snapshot["capacity"] = {"Y1": 10, "Y2": 20}
        snapshot["locked_inventory"] = {
            ("Y1", "OLD1"): 5,
            ("Y2", "OLD2"): 5,
        }
        snapshot["locked_release_local"] = {
            ("Y1", "OLD1"): 10,
            ("Y2", "OLD2"): 10,
        }
        utilization = _horizon_end_block_utilization(snapshot, {})
        self.assertEqual(utilization["K1"], .5)
        self.assertEqual(utilization["K2"], .25)

    def test_solver_diagnostics_are_present_and_cycle_based(self):
        snapshot = objective_snapshot()
        result = solve_rolling_snapshot(
            snapshot,
            time_limit=2,
            configuration="core_start",
            seed=0,
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(
            result["cycle_first_incumbent_wall_time"],
            result["preprocessing_time"],
        )
        for stage in result["stages"]:
            for field in (
                "objective_bound",
                "mip_gap",
                "root_relaxation",
                "solution_count",
                "stage_first_incumbent_time",
                "binary_variables",
            ):
                self.assertIn(field, stage)
        self.assertIn("final_stage_mip_gap", result)
        self.assertIn("final_stage_objective_bound", result)

    def test_dependency_propagation_waits_for_shortage_repair(self):
        result = solve_rolling_snapshot(
            objective_snapshot(),
            time_limit=2,
            configuration="full",
            seed=0,
        )
        self.assertTrue(result["ok"])
        diagnostics = result["impact_diagnostics"]
        self.assertEqual(
            diagnostics["dependency_trigger_mode"],
            "shortage_repair_only",
        )
        self.assertEqual(diagnostics["propagated_pairs"], [])


if __name__ == "__main__":
    unittest.main()

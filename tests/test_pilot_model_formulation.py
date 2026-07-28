import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gurobipy import GRB

from rolling_model import (
    build_rolling_model,
    compute_objective_scales,
    extract_rolling_solution,
    solve_full_horizon_packing_oracle,
    validate_snapshot_temporal_consistency,
)
from rolling_data import (
    aggregate_size_period_pressure_diagnostics,
    build_integer_certified_pressure_case_family,
    build_oracle_certified_case_family,
    build_repair_pressure_case,
    build_synthetic_rolling_case,
    initial_simulation_state,
    optimization_snapshot,
)
from rolling_experiment import run_rolling_case
from rolling_solver import (
    _block_scores,
    _bottleneck_minimal_expansion,
    _direct_impact_pairs,
    _horizon_end_block_utilization,
    _incumbent_decision,
    _restricted_domain_aggregate_capacity_margin,
    _select_aggregate_domain_ladder,
    _snapshot_pressure_diagnostics,
    baseline_residual_capacity_by_bay_period,
    canonical_stability_metrics,
    physical_residual_capacity_by_bay_period,
    solve_rolling_snapshot,
    _validate_rolling_solution_reference,
    validate_rolling_solution,
)
from test_objective_scales_and_occupancy import objective_snapshot
from test_time_scores_and_release_propagation import base_snapshot


def packing_oracle_case(
    *,
    bays: int = 1,
    flow: dict[tuple[str, str, int], int] | None = None,
    releases: dict[str, int] | None = None,
) -> dict:
    bay_names = [f"B01_Y{index + 1:02d}" for index in range(bays)]
    return {
        "bays": bay_names,
        "bay_size": {bay: 20 for bay in bay_names},
        "capacity": {bay: 50 for bay in bay_names},
        "heights": ("STD", "HIGH"),
        "group_attrs": {
            "P1_20_STD": {"pod": "P1", "size": 20, "height": "STD"},
            "P2_20_HIGH": {"pod": "P2", "size": 20, "height": "HIGH"},
        },
        "true_flow": flow or {("V01", "P1_20_STD", 0): 40},
        "planned_ship_release_period": releases or {"V01": 3},
        "realized_ship_release_period": releases or {"V01": 3},
        "locked_initial": {},
        "locked_height_initial": {},
        "old_release_period": {},
    }


class PilotModelFormulationTest(unittest.TestCase):
    def test_aggregate_domain_ladder_selects_smallest_screened_domain(self):
        snapshot = objective_snapshot()
        scores = {
            ("V", "G", block): {"score": 2 - index}
            for index, block in enumerate(snapshot["blocks"])
        }
        level, diagnostics = _select_aggregate_domain_ladder(
            snapshot,
            {("V", "G")},
            set(),
            scores,
            uncertainty_radius=.10,
            time_limit=2,
        )

        self.assertEqual(level, 0)
        self.assertEqual(diagnostics["selected_domain"], "N0")
        self.assertEqual(
            diagnostics["selection_reason"],
            "smallest_aggregate_lp_screened_domain",
        )
        self.assertTrue(diagnostics["screen_is_relaxation"])

    def test_aggregate_domain_ladder_falls_back_to_global_safely(self):
        snapshot = objective_snapshot()
        snapshot["remaining_demand"] = {("V", "G"): 30}
        snapshot["forecast_arrivals"] = {("V", "G", 0): 30}
        scores = {
            ("V", "G", block): {"score": 2 - index}
            for index, block in enumerate(snapshot["blocks"])
        }
        level, diagnostics = _select_aggregate_domain_ladder(
            snapshot,
            {("V", "G")},
            set(),
            scores,
            uncertainty_radius=.10,
            time_limit=2,
        )

        self.assertEqual(level, 3)
        self.assertEqual(diagnostics["selected_domain"], "Global")
        self.assertEqual(
            diagnostics["selection_reason"],
            "global_safety_fallback_without_buffered_domain",
        )

    def test_aggregate_screen_defers_expansion_until_integer_shortage(self):
        snapshot = objective_snapshot()
        diagnostics = {
            "policy": "buffered_aggregate_lp_domain_ladder",
            "selected_level": 1,
            "selected_domain": "N1",
            "selection_reason": "smallest_aggregate_lp_screened_domain",
            "evaluations": [],
            "runtime_seconds": 0.0,
        }
        with patch(
            "rolling_solver._select_aggregate_domain_ladder",
            return_value=(1, diagnostics),
        ):
            result = solve_rolling_snapshot(
                snapshot,
                time_limit=2,
                configuration="full_bottleneck",
                seed=0,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [stage["stage"] for stage in result["stages"]],
            ["aggregate_screened_impact_region"],
        )
        self.assertFalse(result["repair_triggered"])

    def test_aggregate_capacity_margin_distinguishes_robust_and_deficit_domains(self):
        snapshot = objective_snapshot()
        allowed = {("V", "G"): ["Y1"]}
        robust = _restricted_domain_aggregate_capacity_margin(
            snapshot,
            allowed,
            uncertainty_radius=.10,
            time_limit=2,
        )
        self.assertEqual(robust["classification"], "aggregate_margin_pass")
        self.assertFalse(robust["route_to_global"])
        self.assertAlmostEqual(robust["maximum_scale"], 2)

        snapshot["remaining_demand"] = {("V", "G"): 15}
        snapshot["forecast_arrivals"] = {("V", "G", 0): 15}
        deficit = _restricted_domain_aggregate_capacity_margin(
            snapshot,
            allowed,
            uncertainty_radius=.10,
            time_limit=2,
        )
        self.assertEqual(deficit["classification"], "aggregate_nominal_deficit")
        self.assertTrue(deficit["route_to_global"])
        self.assertLess(deficit["maximum_scale_bound"], 1)

    def test_aggregate_capacity_margin_respects_existing_height_lock(self):
        snapshot = objective_snapshot()
        snapshot["group_attrs"]["G"]["height"] = "HIGH"
        snapshot["locked_inventory"] = {("Y1", "OLD"): 1}
        snapshot["locked_height"] = {("Y1", "OLD"): "STD"}
        snapshot["locked_release_local"] = {("Y1", "OLD"): 10}
        result = _restricted_domain_aggregate_capacity_margin(
            snapshot,
            {("V", "G"): ["Y1"]},
            uncertainty_radius=0,
            time_limit=2,
        )

        self.assertEqual(result["classification"], "aggregate_nominal_deficit")
        self.assertAlmostEqual(result["maximum_scale"], 0)

    def test_aggregate_capacity_is_shared_across_ship_groups(self):
        snapshot = objective_snapshot()
        snapshot["remaining_demand"] = {
            ("V", "G"): 6,
            ("V2", "G"): 6,
        }
        snapshot["forecast_arrivals"] = {
            ("V", "G", 0): 6,
            ("V2", "G", 0): 6,
        }
        snapshot["ship_release_local"]["V2"] = 10
        result = _restricted_domain_aggregate_capacity_margin(
            snapshot,
            {
                ("V", "G"): ["Y1"],
                ("V2", "G"): ["Y1"],
            },
            uncertainty_radius=0,
            time_limit=2,
        )

        self.assertEqual(
            result["classification"],
            "aggregate_nominal_deficit",
        )
        self.assertAlmostEqual(result["maximum_scale"], 10 / 12)

    def test_oracle_family_keeps_unknown_boundary_unclassified(self):
        def certificate(case, **_kwargs):
            factor = case["ship_volume_factor"]
            classification = (
                "feasible"
                if factor < 2
                else "overloaded"
                if factor > 3
                else "unknown"
            )
            return {
                "classification": classification,
                "minimum_shortage": 0 if classification == "feasible" else None,
                "incumbent_shortage": 1 if classification == "overloaded" else None,
                "objective_bound": 1 if classification == "overloaded" else 0,
                "shortage_lower_bound": 1 if classification == "overloaded" else 0,
                "proved_optimal": classification == "feasible",
                "zero_shortage_certificate": classification == "feasible",
                "positive_shortage_certificate": classification == "overloaded",
                "solver_status": GRB.TIME_LIMIT,
                "solution_count": 1,
                "runtime_seconds": 0,
                "node_count": 0,
                "total_demand": sum(case["true_flow"].values()),
                "late_flow_quantity": 0,
                "horizon_periods": 1,
                "placement_variable_count": 0,
                "model_variable_count": 0,
                "model_constraint_count": 0,
                "release_basis": "realized",
            }

        with patch(
            "rolling_model.solve_full_horizon_packing_oracle",
            side_effect=certificate,
        ):
            family = build_oracle_certified_case_family(
                seed=1,
                num_blocks=1,
                bays_per_block=4,
                num_ships=1,
                cycles=1,
                initial_utilization=0,
                forecast_error=0,
                containers_per_ship_range=(20, 20),
                active_ship_overlap=1,
                pod_count=1,
                factor_bounds=(1, 4),
                search_iterations=4,
                oracle_time_limit=1,
            )

        self.assertEqual(
            family["tight"]["oracle_certificate"]["classification"],
            "feasible",
        )
        self.assertEqual(
            family["overloaded"]["oracle_certificate"]["classification"],
            "overloaded",
        )
        self.assertTrue(family["calibration"]["search_stopped_due_unknown"])
        self.assertGreater(family["calibration"]["unknown_evaluation_count"], 0)

    def test_oracle_certified_family_separates_pressure_classes(self):
        family = build_oracle_certified_case_family(
            seed=11,
            num_blocks=1,
            bays_per_block=4,
            num_ships=2,
            cycles=2,
            bay_capacity=50,
            initial_utilization=0,
            forecast_error=0,
            containers_per_ship_range=(20, 20),
            active_ship_overlap=2,
            pod_count=1,
            factor_bounds=(.25, 10),
            search_iterations=5,
            oracle_time_limit=5,
        )

        self.assertEqual(
            family["feasible"]["oracle_certificate"]["classification"],
            "feasible",
        )
        self.assertEqual(
            family["tight"]["oracle_certificate"]["classification"],
            "feasible",
        )
        self.assertEqual(
            family["overloaded"]["oracle_certificate"]["classification"],
            "overloaded",
        )
        self.assertLess(
            family["feasible"]["ship_volume_factor"],
            family["tight"]["ship_volume_factor"],
        )
        self.assertLess(
            family["tight"]["ship_volume_factor"],
            family["overloaded"]["ship_volume_factor"],
        )
        self.assertEqual(
            family["tight"]["execution_cycles"],
            family["tight"]["admission_cycles"] + 3,
        )
        self.assertLess(
            max(period for _ship, _group, period in family["tight"]["true_flow"]),
            family["tight"]["execution_cycles"]
            * family["tight"]["execution_periods"],
        )

    def test_aggregate_pressure_diagnostic_is_not_a_feasibility_claim(self):
        case = packing_oracle_case(
            flow={
                ("V01", "P1_20_STD", 0): 30,
                ("V02", "P2_20_HIGH", 0): 30,
            },
            releases={"V01": 3, "V02": 3},
        )
        diagnostics = aggregate_size_period_pressure_diagnostics(case)

        self.assertEqual(diagnostics["peak_load_ratio"], 1.2)
        self.assertEqual(
            diagnostics["metric"],
            "peak_size_period_aggregate_capacity_load_ratio",
        )
        result = solve_full_horizon_packing_oracle(
            case,
            time_limit=5,
            stop_after_classification=False,
        )
        self.assertEqual(result["classification"], "overloaded")

    def test_pressure_target_family_requires_integer_feasible_cases(self):
        family = build_integer_certified_pressure_case_family(
            pressure_targets={"ordinary": .35, "high_pressure": .55},
            seed=13,
            num_blocks=2,
            bays_per_block=4,
            num_ships=2,
            cycles=2,
            bay_capacity=50,
            initial_utilization=.20,
            forecast_error=0,
            containers_per_ship_range=(20, 30),
            active_ship_overlap=2,
            pod_count=1,
            factor_bounds=(.01, 5),
            target_absolute_tolerance=.03,
            search_iterations=10,
            oracle_time_limit=5,
        )

        self.assertEqual(set(family), {"ordinary", "high_pressure"})
        for label, target in {"ordinary": .35, "high_pressure": .55}.items():
            case = family[label]
            self.assertEqual(case["oracle_case_class"], "feasible")
            self.assertTrue(
                case["oracle_certificate"]["zero_shortage_certificate"]
            )
            self.assertLessEqual(
                abs(
                    case["capacity_pressure_diagnostics"]["peak_load_ratio"]
                    - target
                ),
                .03,
            )

    def test_full_horizon_packing_oracle_certifies_integer_feasibility(self):
        result = solve_full_horizon_packing_oracle(
            packing_oracle_case(),
            time_limit=5,
            return_witness=True,
        )

        self.assertEqual(result["classification"], "feasible")
        self.assertTrue(result["zero_shortage_certificate"])
        self.assertEqual(result["minimum_shortage"], 0)
        self.assertEqual(sum(result["placement"].values()), 40)

    def test_full_horizon_packing_oracle_proves_capacity_overload(self):
        case = packing_oracle_case(
            flow={("V01", "P1_20_STD", 0): 60},
        )
        result = solve_full_horizon_packing_oracle(
            case,
            time_limit=5,
            stop_after_classification=False,
        )

        self.assertEqual(result["classification"], "overloaded")
        self.assertTrue(result["proved_optimal"])
        self.assertEqual(result["minimum_shortage"], 10)

    def test_packing_oracle_uses_safe_analytical_overload_certificate(self):
        case = packing_oracle_case(
            flow={("V01", "P1_20_STD", 0): 60},
        )
        result = solve_full_horizon_packing_oracle(
            case,
            time_limit=5,
        )

        self.assertEqual(result["classification"], "overloaded")
        self.assertTrue(result["positive_shortage_certificate"])
        self.assertEqual(result["shortage_lower_bound"], 10)
        self.assertEqual(
            result["certificate_method"],
            "analytical_size_period_capacity_lower_bound",
        )
        self.assertEqual(result["model_variable_count"], 0)

    def test_full_horizon_packing_oracle_enforces_height_and_release(self):
        mixed = packing_oracle_case(
            flow={
                ("V01", "P1_20_STD", 0): 30,
                ("V02", "P2_20_HIGH", 0): 30,
            },
            releases={"V01": 3, "V02": 3},
        )
        mixed_result = solve_full_horizon_packing_oracle(
            mixed,
            time_limit=5,
            stop_after_classification=False,
        )
        self.assertEqual(mixed_result["classification"], "overloaded")
        self.assertEqual(mixed_result["minimum_shortage"], 30)

        reusable = packing_oracle_case(
            flow={
                ("V01", "P1_20_STD", 0): 50,
                ("V02", "P2_20_HIGH", 2): 50,
            },
            releases={"V01": 2, "V02": 4},
        )
        reusable_result = solve_full_horizon_packing_oracle(
            reusable,
            time_limit=5,
        )
        self.assertEqual(reusable_result["classification"], "feasible")
        self.assertEqual(reusable_result["minimum_shortage"], 0)

    def test_full_horizon_packing_oracle_rejects_flow_at_release(self):
        case = packing_oracle_case(
            flow={("V01", "P1_20_STD", 2): 5},
            releases={"V01": 2},
        )
        result = solve_full_horizon_packing_oracle(
            case,
            time_limit=5,
            stop_after_classification=False,
        )

        self.assertEqual(result["classification"], "overloaded")
        self.assertEqual(result["minimum_shortage"], 5)
        self.assertEqual(result["late_flow_quantity"], 5)

    def test_adaptive_pressure_routes_by_snapshot_state_not_size_label(self):
        common = dict(
            seed=700,
            num_blocks=12,
            bays_per_block=10,
            num_ships=16,
            cycles=8,
            containers_per_ship_range=(250, 600),
            active_ship_overlap=4,
            pod_count=8,
            forecast_error=.2,
            forecast_error_mode="mixed",
        )
        ordinary_case = build_synthetic_rolling_case(
            initial_utilization=.55,
            **common,
        )
        severe_case = build_synthetic_rolling_case(
            initial_utilization=.80,
            **common,
        )

        diagnostics = []
        for case in (ordinary_case, severe_case):
            snapshot = optimization_snapshot(
                case,
                initial_simulation_state(case),
            )
            direct, _reasons = _direct_impact_pairs(snapshot, .10)
            diagnostics.append(
                _snapshot_pressure_diagnostics(snapshot, direct)
            )

        self.assertEqual(diagnostics[0]["route"], "bottleneck_repair")
        self.assertEqual(diagnostics[1]["route"], "global_core")
        self.assertGreater(
            diagnostics[1]["pressure_index"],
            diagnostics[0]["pressure_index"],
        )

    def test_incumbent_guard_is_strictly_lexicographic(self):
        incumbent = (10.0, 100.0, 1.0)
        self.assertEqual(
            _incumbent_decision((9.0, 1000.0, 2.0), incumbent),
            (True, "improved_predicted_shortage"),
        )
        self.assertEqual(
            _incumbent_decision((10.0, 99.0, 2.0), incumbent),
            (True, "improved_stability"),
        )
        self.assertEqual(
            _incumbent_decision((10.0, 100.0, .9), incumbent),
            (True, "improved_normalized_operations"),
        )
        self.assertEqual(
            _incumbent_decision((10.0, 101.0, .5), incumbent),
            (False, "not_lexicographically_better"),
        )

    def test_non_dependency_candidate_skips_overwritten_physical_scores(self):
        with patch(
            "rolling_solver._block_scores", wraps=_block_scores
        ) as scorer:
            result = solve_rolling_snapshot(
                objective_snapshot(),
                time_limit=2,
                configuration="full_bottleneck",
                seed=0,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(scorer.call_count, 1)
        self.assertEqual(
            scorer.call_args.kwargs["capacity_basis"],
            "frozen_plan_baseline",
        )

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

    def test_batched_extraction_and_sparse_validation_match_references(self):
        snapshot = objective_snapshot()
        model, variables, expressions = build_rolling_model(
            snapshot,
            objective_scales=compute_objective_scales(snapshot),
        )
        model.Params.OutputFlag = 0
        model.optimize()
        self.assertEqual(model.Status, GRB.OPTIMAL)

        reference_solution = extract_rolling_solution(
            variables,
            expressions,
            snapshot=snapshot,
        )
        batched_solution = extract_rolling_solution(
            variables,
            expressions,
            model=model,
            snapshot=snapshot,
        )
        self.assertEqual(batched_solution, reference_solution)

        for solution in (
            batched_solution,
            copy.deepcopy(batched_solution),
        ):
            if solution is not batched_solution:
                first_key = next(iter(solution["reservation"]))
                solution["reservation"][first_key] += 1
            reference_report = _validate_rolling_solution_reference(
                snapshot,
                solution,
            )
            sparse_report = validate_rolling_solution(snapshot, solution)
            self.assertEqual(
                sparse_report["feasible"],
                reference_report["feasible"],
            )
            self.assertEqual(
                set(sparse_report["violations"]),
                set(reference_report["violations"]),
            )
            self.assertAlmostEqual(
                sparse_report["max_violation"],
                reference_report["max_violation"],
            )
            for name, value in reference_report["violations"].items():
                self.assertAlmostEqual(
                    sparse_report["violations"][name],
                    value,
                    msg=name,
                )
        model.dispose()

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
            epigraph[0]["components"]["normalized_operations_score"],
            exact[0]["components"]["normalized_operations_score"],
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

    def test_bottleneck_selector_opens_minimum_covering_block(self):
        snapshot = objective_snapshot()
        pair = ("V", "G")
        solution = {
            "din": {},
            "shortage": {("V", "G", 0): 5, ("V", "G", 1): 0},
        }
        scores = _block_scores(snapshot)
        allowed, diagnostics = _bottleneck_minimal_expansion(
            snapshot,
            {pair: ["Y1"]},
            solution,
            {pair},
            scores,
            time_limit=.5,
            seed=0,
        )
        self.assertEqual(diagnostics["status"], "cover_found")
        self.assertEqual(diagnostics["selected_pair_block_count"], 1)
        self.assertEqual(diagnostics["selected_pair_blocks"], {"V|G": ["K2"]})
        self.assertEqual(allowed[pair], ["Y1", "Y2"])

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

    def test_shortage_incumbent_enqueues_progressive_repair(self):
        case = build_repair_pressure_case(level="nearby", seed=100)
        self.assertEqual(case["cycles"], 2)
        self.assertEqual(case["num_ships"], 4)
        self.assertEqual(case["pressure_shock_total"], 210)
        result = run_rolling_case(
            case,
            # This is a mechanism-reachability test, not a runtime-limit test.
            # Leave headroom for loaded CI machines so a valid repair path is
            # not mislabeled as a logic failure.
            time_per_cycle=8,
            configuration="full",
            seed=100,
        )
        self.assertTrue(result["ok"])
        repair_cycles = [cycle for cycle in result["cycles"] if cycle.get("repair_triggered")]
        self.assertTrue(repair_cycles)
        self.assertIn(
            "adaptive_repair_1",
            [stage["stage"] for stage in repair_cycles[0]["stages"]],
        )


if __name__ == "__main__":
    unittest.main()

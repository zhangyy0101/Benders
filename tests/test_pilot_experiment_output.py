import json
import tempfile
import unittest
from pathlib import Path

from analysis.summarize_experiments import _number, artifact_audit
from experiment_metadata import write_experiment_artifacts
from run_experiments import (
    _resume_rows,
    experiment_identity,
    pilot_diagnostics,
    planned_experiment_identity,
    stage_summary,
)


class PilotExperimentOutputTest(unittest.TestCase):
    def test_stage_summary_records_residual_shortage_recovery_decisions(self):
        result = {
            "cycles": [
                {
                    "stages": [
                        {
                            "stage": "bottleneck_repair",
                            "global_repair_decision": (
                                "enqueued_residual_shortage"
                            ),
                        },
                        {"stage": "global_repair"},
                    ]
                },
                {
                    "stages": [
                        {
                            "stage": "bottleneck_repair",
                            "global_repair_decision": (
                                "skipped_insufficient_time"
                            ),
                        }
                    ]
                },
            ],
            "total_preprocessing_time": 0,
            "total_solver_time": 0,
            "total_online_decision_time": 0,
            "total_solution_extract_time": 0,
            "total_validation_time": 0,
        }
        summary = stage_summary(result)
        self.assertEqual(summary["final_global_repair_count"], 1)
        self.assertEqual(
            summary["residual_shortage_global_repair_enqueued_count"],
            1,
        )
        self.assertEqual(
            summary["residual_shortage_global_repair_skipped_time_count"],
            1,
        )

    def test_resume_loads_only_matching_checkpoint(self):
        metadata = {"git_commit": "abc", "problem_protocol": "test"}
        matrix = {"seeds": [100]}
        row = {
            "instance": "pilot_medium",
            "num_blocks": 5,
            "bays_per_block": 5,
            "num_ships": 6,
            "cycles": 4,
            "requested_initial_utilization": .55,
            "forecast_error": .1,
            "forecast_error_mode": "mixed",
            "outbound_rate": 150,
            "release_delay_periods": 0,
            "configuration": "full",
            "seed": 100,
            "time_limit": 15.0,
            "ok": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "checkpoint.csv"
            write_experiment_artifacts(
                rows=[row],
                output_csv=output,
                metadata=metadata,
                requested_matrix=matrix,
                expected_row_count=2,
            )
            resumed = _resume_rows(
                output_csv=str(output),
                manifest_output=None,
                metadata=metadata,
                requested_matrix=matrix,
            )
            with self.assertRaisesRegex(ValueError, "metadata differs"):
                _resume_rows(
                    output_csv=str(output),
                    manifest_output=None,
                    metadata={**metadata, "git_commit": "different"},
                    requested_matrix=matrix,
                )
        self.assertEqual(len(resumed), 1)
        self.assertEqual(experiment_identity(resumed[0]), experiment_identity(row))

    def test_planned_identity_matches_result_fields(self):
        case = {
            "num_blocks": 5,
            "bays_per_block": 5,
            "num_ships": 6,
            "cycles": 4,
            "requested_initial_utilization": .55,
            "forecast_error": .1,
            "forecast_error_mode": "mixed",
            "nominal_outbound_rate_per_ship_period": 150,
            "release_delay_periods": 0,
        }
        row = {
            "instance": "pilot_medium",
            **{key: case[key] for key in (
                "num_blocks", "bays_per_block", "num_ships", "cycles",
                "requested_initial_utilization", "forecast_error",
                "forecast_error_mode", "release_delay_periods",
            )},
            "outbound_rate": 150,
            "configuration": "full",
            "seed": 100,
            "time_limit": 15,
        }
        self.assertEqual(
            planned_experiment_identity("pilot_medium", case, "full", 100, 15),
            experiment_identity(row),
        )

    def test_summary_reads_csv_booleans(self):
        self.assertEqual(_number({"ok": "True"}, "ok"), 1.0)
        self.assertEqual(_number({"ok": "False"}, "ok"), 0.0)

    def test_summary_reads_legacy_normalized_score_alias(self):
        row = {"mean_cycle_predicted_operations_cost": "0.625"}
        self.assertEqual(
            _number(row, "mean_cycle_normalized_operations_score"),
            .625,
        )

    def test_artifact_audit_checks_normalized_score_identity(self):
        row = {
            "ok": True,
            "git_dirty": False,
            "weight_profile": json.dumps({
                "operations": {
                    "concentration": 1,
                    "balance": 2,
                    "distance": 3,
                    "in_out_conflict": 4,
                }
            }),
            "mean_cycle_normalized_operations_score": 3.0,
            "mean_cycle_predicted_concentration_normalized": .1,
            "mean_cycle_predicted_occupancy_balance_normalized": .2,
            "mean_cycle_predicted_distance_normalized": .3,
            "mean_cycle_predicted_in_out_conflict_normalized": .4,
        }
        audit = artifact_audit([row])
        self.assertEqual(audit["score_identity_checked_rows"], 1)
        self.assertEqual(audit["score_identity_failure_count"], 0)
        self.assertAlmostEqual(audit["max_score_identity_error"], 0)

    def test_cycle_diagnostics_are_aggregated_for_pilot_analysis(self):
        result = {
            "cycles": [
                {
                    "validation": {"feasible": True},
                    "failure_status": None,
                    "termination_status": "TIME_LIMIT_FEASIBLE",
                    "impact_diagnostics": {
                        "propagated_pairs": [["V1", "G1"], ["V2", "G2"]],
                        "pressure_propagation": [["V1", "G1"]],
                        "release_opportunity_propagation": [["V2", "G2"]],
                        "dependency_edge_count": 4,
                    },
                    "dependency_graph_time": .2,
                    "adaptive_global_bypass": True,
                    "adaptive_pressure": {
                        "pressure_index": 1.2,
                        "peak_load_ratio": .9,
                        "demand_free_capacity_ratio": 1.3,
                        "legacy_route_to_global": False,
                    },
                    "aggregate_domain_ladder_time": .04,
                    "aggregate_domain_ladder": {
                        "policy": "buffered_aggregate_lp_domain_ladder",
                        "selected_domain": "Global",
                        "selection_reason": (
                            "global_safety_fallback_without_buffered_domain"
                        ),
                        "evaluations": [
                            {"domain": "Global", "maximum_scale": 1.05}
                        ],
                    },
                    "repair_triggered": True,
                    "quality_polish_triggered": True,
                    "quality_polish_improved": False,
                    "stages": [
                        {
                            "stage": "global_repair",
                            "dependency_expansion_count": 2,
                            "stability_epigraph_max_slack": 1e-8,
                            "occupancy_balance_epigraph_slack": 4.5,
                        }
                    ],
                },
                {
                    "validation": {"feasible": False},
                    "failure_status": "online_decision_time_limit_exceeded",
                    "termination_status": "DEADLINE_MISS",
                    "impact_diagnostics": {
                        "propagated_pairs": [],
                        "pressure_propagation": [],
                        "release_opportunity_propagation": [],
                        "dependency_edge_count": 2,
                    },
                    "dependency_graph_time": .1,
                    "adaptive_global_bypass": False,
                    "adaptive_pressure": {
                        "pressure_index": .4,
                        "peak_load_ratio": .6,
                        "demand_free_capacity_ratio": .4,
                        "legacy_route_to_global": False,
                    },
                    "aggregate_domain_ladder_time": .02,
                    "aggregate_domain_ladder": {
                        "policy": "buffered_aggregate_lp_domain_ladder",
                        "selected_domain": "N1",
                        "selection_reason": (
                            "smallest_aggregate_lp_screened_domain"
                        ),
                        "evaluations": [
                            {"domain": "N1", "maximum_scale": 1.3}
                        ],
                    },
                    "repair_triggered": False,
                    "quality_polish_triggered": True,
                    "quality_polish_improved": True,
                    "stages": [],
                },
                {"skipped": True},
            ]
        }

        diagnostics = pilot_diagnostics(result)

        self.assertEqual(
            diagnostics["failure_status"],
            "online_decision_time_limit_exceeded",
        )
        self.assertEqual(diagnostics["wall_clock_time_limit_exceeded"], 1)
        self.assertEqual(diagnostics["online_deadline_miss_count"], 1)
        self.assertEqual(diagnostics["time_limit_feasible_count"], 1)
        self.assertEqual(diagnostics["feasible_termination_count"], 0)
        self.assertEqual(diagnostics["validation_failure_count"], 1)
        self.assertEqual(diagnostics["solved_cycle_count"], 2)
        self.assertEqual(diagnostics["propagation_triggered_count"], 1)
        self.assertEqual(diagnostics["propagated_pair_count"], 2)
        self.assertEqual(diagnostics["dependency_expansion_count"], 2)
        self.assertEqual(diagnostics["dependency_edge_count"], 6)
        self.assertAlmostEqual(diagnostics["total_dependency_graph_time"], .3)
        self.assertEqual(diagnostics["pressure_propagation_count"], 1)
        self.assertEqual(diagnostics["release_opportunity_propagation_count"], 1)
        self.assertEqual(diagnostics["global_repair_count"], 1)
        self.assertEqual(diagnostics["adaptive_global_bypass_count"], 1)
        self.assertAlmostEqual(diagnostics["adaptive_global_bypass_rate"], .5)
        self.assertEqual(diagnostics["aggregate_ladder_cycle_count"], 2)
        self.assertEqual(diagnostics["aggregate_ladder_n1_count"], 1)
        self.assertEqual(diagnostics["aggregate_ladder_global_count"], 1)
        self.assertEqual(
            diagnostics["aggregate_ladder_safety_fallback_count"], 1
        )
        self.assertEqual(
            diagnostics["aggregate_ladder_legacy_disagreement_count"], 1
        )
        self.assertAlmostEqual(diagnostics["total_aggregate_ladder_time"], .06)
        self.assertAlmostEqual(
            diagnostics["mean_selected_aggregate_capacity_scale"], 1.175
        )
        self.assertAlmostEqual(diagnostics["mean_adaptive_pressure_index"], .8)
        self.assertAlmostEqual(diagnostics["max_peak_forecast_load_ratio"], .9)
        self.assertAlmostEqual(
            diagnostics["max_demand_free_capacity_ratio"], 1.3
        )
        self.assertEqual(diagnostics["quality_polish_triggered_count"], 2)
        self.assertEqual(diagnostics["quality_polish_improved_count"], 1)
        self.assertAlmostEqual(diagnostics["quality_polish_improvement_rate"], .5)
        self.assertEqual(diagnostics["max_stability_epigraph_slack"], 1e-8)
        self.assertEqual(
            diagnostics["max_occupancy_balance_epigraph_slack"],
            4.5,
        )


if __name__ == "__main__":
    unittest.main()

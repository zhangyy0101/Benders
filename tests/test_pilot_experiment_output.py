import tempfile
import unittest
from pathlib import Path

from analysis.summarize_experiments import _number
from experiment_metadata import write_experiment_artifacts
from run_experiments import (
    _resume_rows,
    experiment_identity,
    pilot_diagnostics,
    planned_experiment_identity,
)


class PilotExperimentOutputTest(unittest.TestCase):
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

    def test_cycle_diagnostics_are_aggregated_for_pilot_analysis(self):
        result = {
            "cycles": [
                {
                    "validation": {"feasible": True},
                    "failure_status": None,
                    "impact_diagnostics": {
                        "propagated_pairs": [["V1", "G1"], ["V2", "G2"]],
                        "pressure_propagation": [["V1", "G1"]],
                        "release_opportunity_propagation": [["V2", "G2"]],
                        "dependency_edge_count": 4,
                    },
                    "dependency_graph_time": .2,
                    "repair_triggered": True,
                    "quality_polish_triggered": True,
                    "quality_polish_improved": False,
                    "stages": [
                        {
                            "stage": "global_repair",
                            "dependency_expansion_count": 2,
                            "stability_epigraph_max_slack": 1e-8,
                        }
                    ],
                },
                {
                    "validation": {"feasible": False},
                    "failure_status": "wall_clock_time_limit_exceeded",
                    "impact_diagnostics": {
                        "propagated_pairs": [],
                        "pressure_propagation": [],
                        "release_opportunity_propagation": [],
                        "dependency_edge_count": 2,
                    },
                    "dependency_graph_time": .1,
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
            diagnostics["failure_status"], "wall_clock_time_limit_exceeded"
        )
        self.assertEqual(diagnostics["wall_clock_time_limit_exceeded"], 1)
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
        self.assertEqual(diagnostics["quality_polish_triggered_count"], 2)
        self.assertEqual(diagnostics["quality_polish_improved_count"], 1)
        self.assertAlmostEqual(diagnostics["quality_polish_improvement_rate"], .5)
        self.assertEqual(diagnostics["max_stability_epigraph_slack"], 1e-8)


if __name__ == "__main__":
    unittest.main()

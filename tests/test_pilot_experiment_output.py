import unittest

from analysis.summarize_experiments import _number
from run_experiments import pilot_diagnostics


class PilotExperimentOutputTest(unittest.TestCase):
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

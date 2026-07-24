import time
import unittest
from collections import defaultdict

from external_baselines import (
    CONFIGURATIONS,
    LITERATURE_CONFIGURATIONS,
    _FeasibleAllocator,
    _dra_reward,
    _jobs,
    _kp_subgradient_prices,
    _preferred_future_blocks,
    solve_literature_baseline,
)
from experiment_metadata import collect_experiment_metadata
from run_experiments import result_row
from rolling_data import (
    build_synthetic_rolling_case,
    initial_simulation_state,
    optimization_snapshot,
)
from rolling_experiment import run_rolling_case


def small_case(**overrides):
    parameters = dict(
        num_blocks=3,
        bays_per_block=4,
        num_ships=3,
        cycles=2,
        containers_per_ship_range=(40, 80),
        active_ship_overlap=2,
        pod_count=2,
        seed=7,
        forecast_error=.1,
        initial_utilization=.25,
    )
    parameters.update(overrides)
    return build_synthetic_rolling_case(**parameters)


class ExternalLiteratureBaselineTest(unittest.TestCase):
    def setUp(self):
        self.case = small_case()
        self.snapshot = optimization_snapshot(
            self.case, initial_simulation_state(self.case)
        )

    def test_all_methods_return_valid_integer_conserving_solutions(self):
        for method in LITERATURE_CONFIGURATIONS:
            with self.subTest(method=method):
                result = solve_literature_baseline(
                    self.snapshot,
                    configuration=method,
                    time_limit=2,
                )
                self.assertTrue(result["ok"])
                self.assertTrue(result["validation"]["feasible"])
                solution = result["solution"]
                self.assertTrue(
                    all(
                        isinstance(value, int)
                        for value in solution["reservation"].values()
                    )
                )
                self.assertTrue(
                    all(
                        isinstance(value, int)
                        for value in solution["din"].values()
                    )
                )
                for ship, group, period in self.snapshot[
                    "forecast_arrivals"
                ]:
                    placed = sum(
                        value
                        for (
                            _bay,
                            item_ship,
                            item_group,
                            item_period,
                        ), value in solution["din"].items()
                        if (
                            item_ship == ship
                            and item_group == group
                            and item_period == period
                        )
                    )
                    self.assertEqual(
                        placed + solution["shortage"][ship, group, period],
                        round(
                            self.snapshot["forecast_arrivals"][
                                ship, group, period
                            ]
                        ),
                    )
                self.assertIsNone(result["final_stage_mip_gap"])
                self.assertEqual(result["stages"][0]["nodes"], 0.0)

    def test_methods_are_deterministic_and_exposed_to_the_cli(self):
        self.assertTrue(set(LITERATURE_CONFIGURATIONS).issubset(CONFIGURATIONS))
        for method in LITERATURE_CONFIGURATIONS:
            with self.subTest(method=method):
                first = solve_literature_baseline(
                    self.snapshot, configuration=method, time_limit=2
                )
                second = solve_literature_baseline(
                    self.snapshot, configuration=method, time_limit=2
                )
                self.assertEqual(
                    first["solution"]["reservation"],
                    second["solution"]["reservation"],
                )
                self.assertEqual(
                    first["solution"]["din"],
                    second["solution"]["din"],
                )

    def test_kp_dos_uses_stage_then_release_priority(self):
        result = solve_literature_baseline(
            self.snapshot, configuration="kp_dos", time_limit=2
        )
        trace = result["baseline_diagnostics"]["priority_trace"]
        priority = [
            (row["period"], row["release"], row["ship"], row["group"])
            for row in trace
        ]
        self.assertEqual(priority, sorted(priority))

    def test_kp_sg_responds_to_shared_block_overload(self):
        case = small_case(
            num_ships=5,
            active_ship_overlap=5,
            containers_per_ship_range=(100, 150),
            initial_utilization=.35,
            seed=11,
        )
        snapshot = optimization_snapshot(
            case, initial_simulation_state(case)
        )
        for ship in snapshot["active_ships"]:
            for index, block in enumerate(snapshot["blocks"]):
                snapshot["distance"][ship, block] = 1 + 5 * index
        prices, _preferred, diagnostics = _kp_subgradient_prices(
            snapshot,
            _FeasibleAllocator(snapshot),
            deadline=time.perf_counter() + .15,
        )
        self.assertGreater(diagnostics["iterations"], 1)
        self.assertGreater(max(diagnostics["overload_trace"]), 0)
        self.assertGreater(diagnostics["positive_multiplier_count"], 0)
        self.assertTrue(any(value > 0 for value in prices.values()))
        self.assertEqual(
            diagnostics["subproblem_ordering"],
            "per_vessel_reverse_arrival_stage",
        )

    def test_dra_uses_equation_27_reward_maximization(self):
        allocator = _FeasibleAllocator(self.snapshot)
        period, _release, ship, group, quantity = _jobs(self.snapshot)[0]
        preferred = _preferred_future_blocks(self.snapshot, allocator)
        scores = {}
        for bay in self.snapshot["bays"]:
            if allocator.feasible_quantity(bay, ship, group, period) <= 0:
                continue
            reward, components = _dra_reward(
                self.snapshot,
                allocator,
                bay=bay,
                ship=ship,
                group=group,
                period=period,
                remaining=quantity,
                history={},
                block_period_pairs=defaultdict(set),
                preferred_future=preferred,
            )
            self.assertAlmostEqual(
                components["total"],
                components["conflict"]
                + components["distance"]
                + components["space"]
                + .5 * components["past"]
                + .5 * components["future"],
            )
            scores[bay] = reward
        result = solve_literature_baseline(
            self.snapshot, configuration="dra_rpm", time_limit=2
        )
        first_decision = result["baseline_diagnostics"]["decisions"][0]
        self.assertAlmostEqual(
            first_decision["reward"]["total"], max(scores.values())
        )
        self.assertEqual(
            result["baseline_diagnostics"]["reward_choice"],
            "maximize_equation_27",
        )

    def test_every_method_runs_through_two_rolling_cycles(self):
        for method in LITERATURE_CONFIGURATIONS:
            with self.subTest(method=method):
                result = run_rolling_case(
                    self.case,
                    configuration=method,
                    time_per_cycle=2,
                    seed=7,
                )
                self.assertTrue(result["ok"])
                solved = [
                    cycle
                    for cycle in result["cycles"]
                    if not cycle.get("skipped")
                ]
                self.assertGreaterEqual(len(solved), 2)
                self.assertTrue(
                    all(
                        cycle["baseline_metadata"]["baseline_protocol"]
                        for cycle in solved
                    )
                )
                self.assertTrue(
                    all("method_state" not in cycle for cycle in solved)
                )

    def test_result_row_records_source_identity(self):
        result = run_rolling_case(
            self.case,
            configuration="kp_dos",
            time_per_cycle=2,
            seed=7,
        )
        metadata = collect_experiment_metadata(
            threads=1,
            mip_gap=.01,
            time_limit=2,
        )
        row = result_row(
            "unit_small",
            self.case,
            "kp_dos",
            7,
            2,
            result,
            metadata,
        )
        self.assertEqual(row["baseline_family"], "Kim-Park 2003")
        self.assertEqual(
            row["baseline_doi"], "10.1016/S0377-2217(02)00333-8"
        )
        self.assertEqual(
            row["baseline_fidelity"], "adapted_algorithmic_core"
        )


if __name__ == "__main__":
    unittest.main()

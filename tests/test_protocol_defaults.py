import inspect
import json
from pathlib import Path

import pytest

import main
import run_experiments
import solve_direct_gurobi
from algorithm_configuration import configuration_hash
from config import PROBLEM_PROTOCOL,Weights
from data import TIME_BUCKET_HOURS
from solver_alns import adaptive_lns
from solver_true_benders import solve_true_benders_pipeline


DEFAULTS_PATH = Path(__file__).parents[1] / "docs" / "paper_exp_v1_defaults.json"


@pytest.fixture(scope="module")
def defaults():
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))


def signature_defaults(function):
    return {
        name: parameter.default
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }


def test_protocol_identity_and_objective_defaults(defaults):
    weights = Weights()
    fixed = defaults["problem_protocol"]
    candidate = defaults["candidate_algorithm_defaults"]
    assert fixed["version"] == PROBLEM_PROTOCOL and fixed["status"] == "fixed"
    assert candidate["status"] == "frozen_candidate"
    assert candidate["algorithm_family"] == "true_bbc_alns"
    assert candidate["problem_protocol_version"] == fixed["version"]
    assert candidate["configuration_name"].startswith("algorithm-candidate-")
    assert fixed["weights"] == {
        "open": weights.master.x,
        "concentration": weights.master.concentration,
        "distance": weights.sub.dist,
        "balance": weights.sub.balance,
        "conflict": weights.sub.conflict,
    }
    assert fixed["objective_scale"] == weights.objective_scale
    assert fixed["time_bucket_hours"] == TIME_BUCKET_HOURS


@pytest.mark.parametrize("build_parser", [main.parser, solve_direct_gurobi.parser, run_experiments.parser])
def test_shared_cli_defaults(defaults, build_parser):
    fixed = defaults["problem_protocol"]
    candidate = defaults["candidate_algorithm_defaults"]
    args = build_parser().parse_args([])
    assert args.alloc_domain == fixed["allocation_domain"]
    assert args.handling_rate_scale == fixed["handling_rate_scale"]
    assert args.old_outbound_release_policy == fixed["old_outbound_release_policy"]
    assert args.threads == candidate["threads"]


def test_solver_gap_seed_and_concentration_cli_defaults(defaults):
    fixed = defaults["problem_protocol"]
    candidate = defaults["candidate_algorithm_defaults"]
    bbc = main.parser().parse_args([])
    direct = solve_direct_gurobi.parser().parse_args([])
    experiments = run_experiments.parser().parse_args([])
    assert bbc.mip_gap == direct.mip_gap == experiments.mip_gap == candidate["mip_gap"]
    assert bbc.seed == candidate["seed"] and experiments.seeds == [candidate["seed"]]
    assert bbc.concentration_mode == direct.concentration_mode == fixed["concentration_mode"]


def test_bbc_phase_share_defaults_match_cli_and_solver(defaults):
    expected = defaults["candidate_algorithm_defaults"]["bbc_phase_shares"]
    args = main.parser().parse_args([])
    config = main.resolve_configuration(args)
    assert expected == {
        "root": config["phase_shares"]["root"],
        "warm": config["phase_shares"]["warm"],
        "alns": config["phase_shares"]["alns"],
        "main": config["phase_shares"]["main"],
    }


def test_direct_alns_phase_share_defaults_match_solver(defaults):
    expected = defaults["candidate_algorithm_defaults"]["direct_alns_phase_shares"]
    signature = signature_defaults(solve_direct_gurobi.solve_direct_alns_pipeline)
    actual = {
        "warm": signature["warm_start_time_share"],
        "alns": signature["alns_time_share"],
    }
    actual["main"] = 1.0 - actual["warm"] - actual["alns"]
    assert expected == actual


def test_candidate_switches_and_alns_defaults_match_cli(defaults):
    candidate = defaults["candidate_algorithm_defaults"]
    args = main.parser().parse_args([])
    config = main.resolve_configuration(args)
    assert {
        "root_prepass": config["root_prepass"],
        "warm_start": config["warm_start"],
        "alns": config["alns"],
        "aggregate_recourse_lb": config["aggregate_recourse_lb"],
        "analytic_recourse_lb": config["analytic_recourse_lb"],
        "valid_inequalities": config["valid_inequalities"],
        "node_cuts": config["node_cuts"],
        "cut_strategy": config["cut_strategy"],
    } == {key: candidate[key] for key in (
        "root_prepass", "warm_start", "alns", "aggregate_recourse_lb",
        "analytic_recourse_lb", "valid_inequalities", "node_cuts", "cut_strategy",
    )}
    alns = candidate["alns_parameters"]
    assert config["alns_parameters"] == alns
    signature = signature_defaults(adaptive_lns)
    assert alns["repair_gap"] == signature["repair_gap"]
    assert alns["destination_ratio"] == signature["destination_ratio"]


def test_fixed_and_provisional_namespaces_do_not_overlap(defaults):
    fixed = set(defaults["problem_protocol"])
    provisional = set(defaults["candidate_algorithm_defaults"])
    assert fixed.isdisjoint(provisional - {"status"})


def test_configuration_hash_is_stable_and_covers_every_setting(defaults):
    candidate = defaults["candidate_algorithm_defaults"]
    reordered = dict(reversed(list(candidate.items())))
    assert configuration_hash(candidate) == configuration_hash(reordered)
    changed = json.loads(json.dumps(candidate))
    changed["alns_parameters"]["repair_time"] += 1
    assert configuration_hash(candidate) != configuration_hash(changed)
    assert len(configuration_hash(candidate)) == 64

import inspect
import json
from pathlib import Path

import pytest

import main
import run_experiments
import solve_direct_gurobi
from config import Weights
from data import TIME_BUCKET_HOURS
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
    assert defaults["protocol_version"] == "paper-exp-v1"
    assert defaults["weights"] == {
        "open": weights.master.x,
        "concentration": weights.master.concentration,
        "distance": weights.sub.dist,
        "balance": weights.sub.balance,
        "conflict": weights.sub.conflict,
    }
    assert defaults["objective_scale"] == weights.objective_scale
    assert defaults["time_bucket_hours"] == TIME_BUCKET_HOURS


@pytest.mark.parametrize("build_parser", [main.parser, solve_direct_gurobi.parser, run_experiments.parser])
def test_shared_cli_defaults(defaults, build_parser):
    args = build_parser().parse_args([])
    assert args.alloc_domain == defaults["allocation_domain"]
    assert args.handling_rate_scale == defaults["handling_rate_scale"]
    assert args.old_outbound_release_policy == defaults["old_outbound_release_policy"]
    assert args.threads == defaults["threads"]


def test_solver_gap_seed_and_concentration_cli_defaults(defaults):
    bbc = main.parser().parse_args([])
    direct = solve_direct_gurobi.parser().parse_args([])
    experiments = run_experiments.parser().parse_args([])
    assert bbc.mip_gap == direct.mip_gap == experiments.mip_gap == defaults["default_solver_gap"]
    assert bbc.seed == defaults["seed"] and experiments.seeds == [defaults["seed"]]
    assert bbc.concentration_mode == direct.concentration_mode == defaults["concentration_mode"]


def test_bbc_phase_share_defaults_match_cli_and_solver(defaults):
    expected = defaults["bbc_phase_shares"]
    args = main.parser().parse_args([])
    assert expected == {
        "root": args.root_time_share,
        "warm": args.warm_start_time_share,
        "alns": args.alns_time_share,
        "main": args.main_bbc_time_share,
    }
    signature = signature_defaults(solve_true_benders_pipeline)
    assert expected == {
        "root": signature["root_time_share"],
        "warm": signature["warm_start_time_share"],
        "alns": signature["alns_time_share"],
        "main": signature["main_bbc_time_share"],
    }


def test_direct_alns_phase_share_defaults_match_solver(defaults):
    expected = defaults["direct_alns_phase_shares"]
    signature = signature_defaults(solve_direct_gurobi.solve_direct_alns_pipeline)
    actual = {
        "warm": signature["warm_start_time_share"],
        "alns": signature["alns_time_share"],
    }
    actual["main"] = 1.0 - actual["warm"] - actual["alns"]
    assert expected == actual

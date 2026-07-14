import main
from scripts import run_candidate_experiments


def test_candidate_entrypoint_defaults():
    args = run_candidate_experiments.parser().parse_args([])
    assert args.suite_dir == "benchmarks/paper_exp_v1_pilot21"
    assert args.algorithm_config == "algorithm-candidate-v1"
    assert args.seeds == [0] and args.threads == 1 and args.mip_gap == .03


def test_main_defaults_to_frozen_candidate():
    args = main.parser().parse_args([])
    config = main.resolve_configuration(args)
    assert args.algorithm_config == "algorithm-candidate-v1"
    assert config["status"] == "frozen_candidate"


def test_main_override_gets_new_identity(capsys):
    args = main.parser().parse_args(["--valid-inequalities"])
    config = main.resolve_configuration(args)
    assert config["status"] == "development_override"
    assert config["configuration_name"] != "algorithm-candidate-v1"
    assert config["configuration_hash"] != "fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce"
    assert "WARNING" in capsys.readouterr().err


def test_legacy_full_remains_explicitly_available():
    args = main.parser().parse_args(["--algorithm-config", "bbc_full_current"])
    assert main.resolve_configuration(args)["configuration_name"] == "bbc_full_current"

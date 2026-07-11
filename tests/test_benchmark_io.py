import copy
import json

import pytest

import main
import run_experiments
import solve_direct_gurobi
from benchmark_io import (
    canonical_instance_payload, compare_instances, instance_digest, load_instance,
    save_instance,
)
from data import prepare_instance, validate_instance_units
from instance_registry import build_builtin_instance, resolve_instance
from synthetic_instance_generator import SyntheticInstanceSpec, generate_synthetic_instance


def generated():
    spec = SyntheticInstanceSpec(
        "io_test", 3, 4, 50, 2, 2, 2, 5, 6, 1.1, 25,
        (.1, .2), (.02, .08), (.1, .2), (35, 50), .7, (.4, .6), .5,
    )
    return generate_synthetic_instance(spec, 51)


@pytest.mark.parametrize("raw", [build_builtin_instance("tiny"), build_builtin_instance("3new6old"), generated()])
def test_round_trip_restores_all_model_data_and_tuple_keys(tmp_path, raw):
    path = tmp_path / "instance.json"
    metadata = save_instance(raw, path)
    loaded = load_instance(path)
    assert metadata["schema_version"] == "yard-bay-instance-v1"
    assert compare_instances(raw, loaded)["equal"]
    assert instance_digest(raw) == instance_digest(loaded) == metadata["digest"]
    assert all(isinstance(key, tuple) for key in loaded["Dist"])
    assert all(isinstance(key, tuple) for key in loaded["Arrivals_interval"])
    validate_instance_units(prepare_instance(loaded))


def test_digest_is_order_independent_but_model_changes_are_detected():
    raw = generated()
    reordered = dict(reversed(list(raw.items())))
    reordered["Dist"] = dict(reversed(list(raw["Dist"].items())))
    assert instance_digest(raw) == instance_digest(reordered)
    changed = copy.deepcopy(raw)
    key = next(iter(changed["Arrivals_interval"]))
    changed["Arrivals_interval"][key] += 1
    assert instance_digest(raw) != instance_digest(changed)
    assert not compare_instances(raw, changed)["equal"]


def test_tamper_and_unknown_top_level_fields_fail(tmp_path):
    path = tmp_path / "instance.json"
    save_instance(generated(), path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["data"]["Alpha"] += .1
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        load_instance(path)
    document["digest"] = instance_digest(load_instance(path, verify_digest=False))
    document["unknown"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="extra=.*unknown"):
        load_instance(path)


def test_prepared_instances_and_unregistered_tuple_maps_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="only raw instances"):
        save_instance(prepare_instance(build_builtin_instance("tiny")), tmp_path / "prepared.json")
    bad = build_builtin_instance("tiny")
    bad["UnknownTupleMap"] = {("a", "b"): 1}
    with pytest.raises(TypeError, match="unregistered dictionary"):
        canonical_instance_payload(bad)
    bad = build_builtin_instance("tiny")
    bad["algorithm_configuration"] = {"threads": 1}
    with pytest.raises(ValueError, match="algorithm configuration is not instance data"):
        save_instance(bad, tmp_path / "algorithm.json")


def test_registry_builtin_and_file_resolve_to_equivalent_prepared_data(tmp_path):
    raw = build_builtin_instance("tiny_concentration")
    path = tmp_path / "tiny.json"
    save_instance(raw, path)
    builtin = prepare_instance(resolve_instance(builtin_name="tiny_concentration"))
    from_file = prepare_instance(resolve_instance(instance_file=path))
    assert compare_instances(builtin, from_file)["equal"]
    with pytest.raises(ValueError, match="exactly one"):
        resolve_instance()
    with pytest.raises(ValueError, match="exactly one"):
        resolve_instance(builtin_name="tiny", instance_file=path)


@pytest.mark.parametrize("build_parser,old_option", [
    (main.parser, "--instance"),
    (solve_direct_gurobi.parser, "--instance"),
    (run_experiments.parser, "--instances"),
])
def test_cli_sources_are_mutually_exclusive(build_parser, old_option):
    with pytest.raises(SystemExit):
        build_parser().parse_args([old_option, "tiny", "--instance-file", "x.json"])

import pytest

from instance_registry import (
    BUILTIN_INSTANCES,
    build_builtin_instance,
    get_builtin_instance_factory,
    list_builtin_instances,
)


def test_builtin_names_are_complete_and_unique():
    names = list_builtin_instances()
    assert names == ("tiny", "tiny_concentration", "3new6old")
    assert len(names) == len(set(names)) == len(BUILTIN_INSTANCES)


@pytest.mark.parametrize("name", list_builtin_instances())
def test_factory_returns_independent_instances(name):
    first = build_builtin_instance(name)
    second = get_builtin_instance_factory(name)()
    assert first == second
    assert first is not second
    first["ScenarioName"] = "mutated"
    assert build_builtin_instance(name)["ScenarioName"] != "mutated"


def test_unknown_builtin_has_clear_error():
    with pytest.raises(KeyError, match="unknown built-in instance.*available"):
        build_builtin_instance("missing")

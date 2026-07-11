"""Registry for the small set of built-in Route-B instances."""
from __future__ import annotations

from collections.abc import Callable

from data import (
    get_data_3new6old_fixed,
    get_data_tiny_benders,
    get_data_tiny_concentration,
)

InstanceFactory = Callable[[], dict]

BUILTIN_INSTANCES: dict[str, InstanceFactory] = {
    "tiny": get_data_tiny_benders,
    "tiny_concentration": get_data_tiny_concentration,
    "3new6old": get_data_3new6old_fixed,
}


def list_builtin_instances() -> tuple[str, ...]:
    """Return built-in names in their stable CLI display order."""
    return tuple(BUILTIN_INSTANCES)


def get_builtin_instance_factory(name: str) -> InstanceFactory:
    """Return the factory for *name*, with a useful error for unknown names."""
    try:
        return BUILTIN_INSTANCES[name]
    except KeyError as exc:
        choices = ", ".join(list_builtin_instances())
        raise KeyError(f"unknown built-in instance {name!r}; available: {choices}") from exc


def build_builtin_instance(name: str) -> dict:
    """Build a fresh raw instance."""
    return get_builtin_instance_factory(name)()


def resolve_instance(*, builtin_name=None, instance_file=None) -> dict:
    """Resolve exactly one built-in name or raw benchmark JSON file."""
    if (builtin_name is None) == (instance_file is None):
        raise ValueError("provide exactly one of builtin_name or instance_file")
    if instance_file is not None:
        from benchmark_io import load_instance
        return load_instance(instance_file)
    return build_builtin_instance(builtin_name)

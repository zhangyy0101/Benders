"""Canonical identity helpers for provisional algorithm configurations."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_configuration_json(configuration: Mapping) -> str:
    """Serialize a configuration deterministically without platform whitespace."""
    if not isinstance(configuration, Mapping):
        raise TypeError("algorithm configuration must be a mapping")
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configuration_hash(configuration: Mapping) -> str:
    """Return the SHA-256 identity of every configuration field and value."""
    payload = canonical_configuration_json(configuration).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

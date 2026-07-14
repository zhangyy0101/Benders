"""Canonical identity helpers for provisional algorithm configurations."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

FROZEN_CANDIDATE_V1_HASH = "fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce"
FROZEN_CANDIDATE_V1_FIELDS = {
    "configuration_name": "algorithm-candidate-v1",
    "configuration_version": "1",
    "status": "frozen_candidate",
    "root_prepass": False,
    "warm_start": False,
    "alns": False,
    "aggregate_recourse_lb": True,
    "analytic_recourse_lb": False,
    "valid_inequalities": False,
    "node_cuts": False,
    "cut_strategy": "standard",
    "phase_shares": {"root": 0.0, "warm": 0.0, "alns": 0.0, "main": 1.0},
}
VALID_AGGREGATE_RELAXATION_LEVELS = {"size", "pod_size"}
VALID_INEQUALITY_PROFILES = {"common", "compact"}


def canonical_configuration_json(configuration: Mapping) -> str:
    """Serialize a configuration deterministically without platform whitespace."""
    if not isinstance(configuration, Mapping):
        raise TypeError("algorithm configuration must be a mapping")
    return json.dumps(configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def configuration_hash(configuration: Mapping) -> str:
    """Return the SHA-256 identity of every configuration field and value."""
    payload = canonical_configuration_json(configuration).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def configuration_payload(configuration: Mapping) -> dict:
    """Return the hashable payload without mutating or backfilling legacy fields."""
    return {key: value for key, value in configuration.items() if key != "configuration_hash"}


def resolved_algorithm_label(configuration: Mapping) -> str:
    """Return a truthful display label without changing configuration identity."""
    name = configuration.get("configuration_name")
    aggregate_level = configuration.get("aggregate_relaxation_level", "size")
    valid_profile = configuration.get("valid_inequality_profile", "common")
    if name == "algorithm-candidate-v1":
        return "aggregate_strengthened_bbc"
    if aggregate_level == "pod_size":
        return "pod_size_aggregate_strengthened_bbc"
    if configuration.get("valid_inequalities") and valid_profile == "compact":
        return "aggregate_strengthened_bbc_with_compact_valid_inequalities"
    if configuration.get("alns") or configuration.get("warm_start") or configuration.get("root_prepass"):
        return "true_bbc_alns_legacy"
    return "aggregate_strengthened_bbc" if configuration.get("aggregate_recourse_lb") else "exact_bbc_core"


def validate_algorithm_configuration(configuration: Mapping) -> dict:
    """Validate configuration semantics while preserving backward-compatible payloads."""
    if not isinstance(configuration, Mapping):
        raise TypeError("algorithm configuration must be a mapping")
    shares = configuration.get("phase_shares", {})
    required = ("root", "warm", "alns", "main")
    if any(key not in shares for key in required):
        raise ValueError("phase_shares must define root, warm, alns, and main")
    if any(float(shares[key]) < 0 for key in required) or sum(float(shares[key]) for key in required) > 1 + 1e-9:
        raise ValueError("phase shares must be non-negative and sum to at most 1")
    if configuration.get("alns") and not configuration.get("warm_start"):
        raise ValueError("ALNS requires warm_start")
    aggregate_level = configuration.get("aggregate_relaxation_level", "size")
    if aggregate_level not in VALID_AGGREGATE_RELAXATION_LEVELS:
        raise ValueError(f"unknown aggregate_relaxation_level {aggregate_level!r}")
    valid_profile = configuration.get("valid_inequality_profile", "common")
    if valid_profile not in VALID_INEQUALITY_PROFILES:
        raise ValueError(f"unknown valid_inequality_profile {valid_profile!r}")
    payload = configuration_payload(configuration)
    actual_hash = configuration_hash(payload)
    supplied_hash = configuration.get("configuration_hash")
    if supplied_hash is not None and supplied_hash != actual_hash:
        raise ValueError("configuration_hash does not match configuration payload")
    if configuration.get("status") == "frozen_candidate":
        if configuration.get("configuration_name") != "algorithm-candidate-v1":
            raise ValueError("only algorithm-candidate-v1 may use frozen_candidate status")
        for key, expected in FROZEN_CANDIDATE_V1_FIELDS.items():
            if configuration.get(key) != expected:
                raise ValueError(f"frozen candidate field {key!r} differs from manifest")
        if actual_hash != FROZEN_CANDIDATE_V1_HASH:
            raise ValueError("frozen candidate hash differs from immutable manifest")
    return dict(configuration)

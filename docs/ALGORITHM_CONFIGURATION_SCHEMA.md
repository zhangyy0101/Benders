# Algorithm configuration schema

Every algorithm result is identified by a canonical configuration payload and SHA-256 hash. The fixed problem protocol and algorithm configuration are separate identities.

## Core fields

Registered BBC configurations explicitly record:

- `configuration_name`, `configuration_version`, `status`, and `algorithm_family`;
- `root_prepass`, `warm_start`, `alns`, `aggregate_recourse_lb`, `analytic_recourse_lb`, `valid_inequalities`, and `node_cuts`;
- `cut_strategy`, `phase_shares`, and `alns_parameters`.

Phase shares must be non-negative and sum to at most one. ALNS requires warm start. Runtime overrides create a new `development_override` name, version, status, and hash.

## Aggregate and valid-inequality profiles

Candidate-v2 development adds two optional fields:

| Field | Registered values | Backward-compatible default |
|---|---|---|
| `aggregate_relaxation_level` | `size`, `pod_size` | `size` |
| `valid_inequality_profile` | `common` | `common` |

Readers use `configuration.get` defaults. These fields are never written into the frozen candidate-v1 payload, so its hash remains unchanged.

The `common` valid-inequality profile contains only ship-size-period handling capacity, minimum compatible open bays, and open-state monotonicity when no new-container outbound demand exists. It does not contain reserve-cover cuts.

## Frozen candidate-v1

`algorithm-candidate-v1` is immutable and resolves to size-level aggregate BBC with no analytic LB, valid inequalities, root, warm, ALNS, or node cuts. Its hash is:

```text
fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce
```

## Candidate-v2 development configurations

| Configuration | Aggregate level | Common valid inequalities | Status |
|---|---|---:|---|
| `V2A_valid` | size | enabled | `development_candidate_v2` |
| `V2B_pod_size_aggregate` | POD-size | disabled | `development_candidate_v2` |
| `V2C_pod_size_aggregate_valid` | POD-size | enabled | `development_candidate_v2` |

All three use configuration version `2-dev`, reference `algorithm-candidate-v1` as their base, have distinct hashes, and keep analytic LB, root, warm, ALNS, and node cuts disabled. None is a frozen candidate-v2.

## Result identity and history

The run identity includes protocol, instance digest, method, configuration hash, seed, budget, threads, MIP gap, allocation domain, weights, and preparation policy. Results additionally store configuration name/version/status, resolved display label, commit, and dirty-worktree state.

Historical C0–C8 and `bbc_*` configurations remain readable for old evidence. They are not current candidate-v2 configurations and must not be mixed with V2 results.

`final_algorithm_frozen` remains `false`.

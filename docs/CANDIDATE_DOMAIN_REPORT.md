# Candidate Domain Stage Report

## Decision

Stage 02 status: **PASS**.

The deterministic candidate block/bay domain generator and its necessary coverage checks are implemented. Stage 03 may consume these domains; no restricted monolithic repair is implemented in this stage.

## Scope delivered

- Added `build_candidate_domain(...)` in `candidate_domain.py`.
- Candidate blocks are selected by `(ship, size)` using aggregate `z`, allocation support, `x` support, capacity, handling, distance, pressure, and stable IDs in the prescribed lexicographic order.
- Positive allocation-support blocks are protected from the normal block cap. A backup block is included when available.
- Candidate bays are selected by `(ship, group)` and only from size-compatible bays.
- Positive group allocation support is preserved; selected blocks, resource slack, distance, pressure, and stable IDs determine the remaining order.
- Individual reserve and handling coverage is checked for every ship-group-period. Bays are appended in ranking order until the necessary conditions pass.
- Soft caps may be exceeded for guide support or structural coverage, with recorded reasons.
- Expansion levels 0, 1, and 2 are implemented. Level 1 adds a block and two bays when available; level 2 uses full aggregate mass, adds three further bays, and raises the fraction soft cap to 0.60.
- Added `check_joint_candidate_feasibility(...)`, an objective-free continuous LP containing reserve allocation, arrival flow, inventory, storage, bay reserve capacity, and ship-bay handling constraints.
- The joint LP creates no objective components, concentration variables, workload variables, or binary variables.
- A proven joint infeasibility causes one deterministic expansion to the complete compatible bay domain and a single recheck. `unknown` never triggers expansion.

## Verification

- Stage-02 focused tests: **10 passed**.
- Full regression suite: **172 passed**.
- `git diff --check`: **PASS**.
- Candidate-v1 hash remains `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`.
- Tests cover static fallback, fractional guide support, allocation support outside the top-z block, multi-bay coverage, soft-cap exceptions, expansion monotonicity, joint infeasibility, and deterministic output.

## Domain audit

| Instance | Guide source | Individual | Joint | Candidate/full group-bay pairs | Ratio | Joint expansion |
|---|---|---|---|---:|---:|---:|
| tiny | `mip_incumbent` | PASS | feasible | 4 / 4 | 1.0000 | 0 |
| XS01 | `mip_incumbent` | PASS | feasible | 15 / 15 | 1.0000 | 0 |
| XS02 | `mip_incumbent` | PASS | feasible | 15 / 15 | 1.0000 | 0 |
| XS03 | `mip_incumbent` | PASS | feasible | 15 / 15 | 1.0000 | 0 |
| S01 | `mip_incumbent` | PASS | feasible | 60 / 120 | 0.5000 | 0 |
| M01 | `mip_incumbent` | PASS | feasible | 156 / 930 | 0.1677 | 0 |
| L01 | `static_fallback` | PASS | feasible | 6320 / 6320 | 1.0000 | 1 |

Audit status: **PASS**.

- No instance has a zero-candidate group.
- All individual coverage checks pass.
- Every final joint coverage status is `feasible`.
- Repeated construction from the same guide is deterministic on every audited instance.
- Candidate pair ratios are recorded.
- L01 uses the complete set of compatible bays after its static initial domain was proven jointly infeasible; it does not use a single-bay assumption.

The full-domain L01 fallback is intentionally conservative. It preserves structural feasibility and records the expansion instead of treating a soft size target as a correctness constraint.

Machine-readable evidence is stored in `validation/candidate_domain_audit/`.

## Stage boundary

Stage 02 stops here. No repair variables, repair objective, exact recourse evaluation, UB, or BBC integration were added.

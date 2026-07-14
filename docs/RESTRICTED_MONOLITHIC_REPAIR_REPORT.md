# Restricted Monolithic Repair Stage Report

## Decision

Stage 03 status: **PASS**.

The exact restricted monolithic repair model and independent incumbent verification path are implemented. This stage does not integrate repair with BBC and does not constitute the standalone AGFR stage.

## Scope delivered

- Refactored `model_monolithic.py` around one shared `_build_monolithic_model(...)` implementation.
- `build_monolithic_model(...)` retains the full-model default path.
- Added `build_restricted_monolithic_model(...)` with `allowed_group_bays` indexed by `(ship, group)`.
- Restricted allocation, arrival-flow, and inventory variables exist only for allowed `(bay, ship, group)` triples.
- Restricted `x` variables exist only for ship-bay pairs serving at least one candidate group.
- Block flow, total workload, average workload, and L1 balance variables retain their complete required indices.
- All original constraints and the exact original objective are shared by the full and restricted builders.
- No guide or candidate preference penalty was introduced.

## Concentration compatibility

- `concentration_metadata(...)` and `build_joint_group_concentration(...)` accept an optional candidate domain.
- Restricted concentration binaries are created only for retained candidate triples.
- Big-M values retain the original capacity/reserve logic.
- The normalization scale is always computed from the complete original feasible-bay domain, so candidate restriction cannot change the business objective scale.
- Default `allowed_group_bays=None` behavior remains unchanged.

## Repair solve and exact verification

Added `solve_restricted_monolithic_repair(...)` in `solver_restricted_repair.py`.

- Retained guide `x` and `alloc_boxes` values are supplied only as partial MIP starts.
- Guide-positive variables are never fixed.
- Extracted repair solutions remain sparse; checker and evaluator use missing-key-as-zero semantics.
- Every incumbent is checked by `validate_solution` and evaluated by `evaluate_common_solution`.
- The repair objective must match the common evaluator core cost within tolerance.
- `GlobalRecourseOracle` fixes the sparse first-stage `x/alloc_boxes` point and re-solves exact recourse.
- Canonical UB is computed as exact first-stage cost plus oracle recourse.
- Canonical UB may not exceed the repair objective beyond tolerance, and the returned solution uses the oracle recourse variables.

Returned diagnostics include candidate/full pair counts and ratio, restricted and estimated-full variable counts, restricted constraint count, model-build runtime, optimization runtime, checker results, and oracle consistency fields.

## Full-domain equivalence gate

| Instance | Optimum | Objective components | Checker | Concentration scale | Variable-domain semantics |
|---|---|---|---|---|---|
| tiny | MATCH | MATCH | PASS | MATCH | MATCH |
| tiny_concentration | MATCH | MATCH | PASS | MATCH | MATCH |
| XS01 | MATCH | MATCH | PASS | MATCH | MATCH |

The restricted full-compatible domain omits variables that are fixed to zero by size compatibility in the legacy full formulation; retained variables have matching types and bounds. This is the intended sparse mathematical equivalence.

## Verification

- Stage-03 focused tests: **8 passed**.
- Existing full-model/concentration/sparse regression subset before the stage gate: **26 passed**.
- Full regression suite: **180 passed**.
- `git diff --check`: **PASS**.
- Candidate-v1 master and configuration payload were not modified.
- Candidate-v1 hash remains `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`.

The dedicated tests cover restricted indexing, full-domain equivalence, exact objective matching, fixed concentration scaling, sparse downstream safety, and oracle canonicalization.

## Stage boundary

Stage 03 stops here. No BBC integration, ALNS, new business weight, candidate-v1 master change, or long S/M/L screen was performed.

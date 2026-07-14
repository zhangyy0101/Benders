# Aggregate Guide Stage Report

## Decision

Stage 01 status: **PASS**.

The standalone Aggregate Guide is implemented and may be used as input to Stage 02. This report does not authorize any later stage beyond the candidate-domain generator.

## Scope delivered

- Added `solver_aggregate_guide.solve_aggregate_guide` with the required public interface.
- The guide uses the candidate-v1 master settings: integer master, size-level aggregate recourse relaxation, no analytic lower bound, and no common valid inequalities.
- MIP parameters are `MIPFocus=1`, `Heuristics=0.5`, `MIPGap=0.10`, with caller-controlled threads and seed.
- Model construction, MIP optimization, and optional LP fallback share one wall-clock deadline.
- A MIP point is preferred; an LP is attempted only when no MIP point exists and time remains; otherwise an always-successful static fallback supplies empty support maps.
- Extracted data consists only of `x`, `alloc_boxes`, aggregate `z`, and support diagnostics. The reported objective is named `guide_objective`; it is not an exact UB.
- No recourse oracle, repair model, candidate-domain generator, or BBC integration was added.

## Support definitions

With tolerance `1e-7`, diagnostics implement:

- `aggregate_flow_by_ship_size_block[(j,s,k)] = sum_n z[j,k,s,n]`;
- `alloc_support_by_ship_group_bay[(j,g,i)] = {max: max_n a[i,j,g,n], sum: sum_n a[i,j,g,n]}`;
- `x_support_by_ship_bay[(j,i)] = sum_n duration[n] * x[i,j,n]`.

Positive and fractional counts are included for `x`, `alloc_boxes`, and aggregate `z` as required.

## Verification

- Aggregate Guide tests: **8 passed**.
- Full regression suite: **162 passed**.
- `git diff --check`: **PASS**.
- Candidate-v1 hash: `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce` (**unchanged**).
- Recourse isolation is covered by a test that replaces `GlobalRecourseOracle` with a failing sentinel.
- MIP extraction, LP fallback, static fallback, fixed-seed behavior, zero-budget deadline behavior, and support formulas are covered by dedicated tests.

## Smoke gate

| Instance | Budget | Source | Status | Runtime | Positive x / alloc / z |
|---|---:|---|---|---:|---:|
| tiny | 0.50 s | `mip_incumbent` | OPTIMAL | 0.009 s | 4 / 4 / 4 |
| XS01 | 0.50 s | `mip_incumbent` | OPTIMAL | 0.060 s | 24 / 60 / 10 |
| S01 | 0.75 s | `mip_incumbent` | TIME_LIMIT | 0.758 s | 110 / 399 / 31 |
| M01 | 2.00 s | `mip_incumbent` | TIME_LIMIT | 2.039 s | 218 / 554 / 64 |
| L01 | 5.00 s | `static_fallback` | TIME_LIMIT | 5.070 s | 0 / 0 / 0 |

Smoke status: **PASS** with zero exceptions and a valid guide source for all five instances. L01 did not produce a MIP incumbent within the shared deadline, so it correctly returned `static_fallback`; its budget was not extended and no fresh LP budget was granted. Small runtime overshoot is solver/model cleanup overhead after the optimization deadline.

Machine-readable evidence is stored under `validation/aggregate_guide_smoke/`.

## Stage boundary

Stage 01 stops here. Candidate sets and restricted monolithic repair remain unimplemented, and candidate-v1/BBC execution paths remain unchanged.

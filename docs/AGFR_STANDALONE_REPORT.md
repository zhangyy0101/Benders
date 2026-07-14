# Standalone AGFR Gate Report

## Decision

Stage 04 status: **PASS**.

```json
{
  "approved_for_bbc_integration": true
}
```

Standalone AGFR satisfies the mandatory safety, runtime, and domain-reduction gates on all eight development instances.

## Failure diagnosis and correction

The first gate was 7/8 because L01 returned no incumbent. The correction addressed three concrete causes without relaxing any gate:

1. The large aggregate guide could not finish model construction and optimization usefully within its 5-second cap. A deterministic size/deadline guard now returns static support immediately and gives unused time back to later phases.
2. Static bay rankings concentrated many groups on the same bays. When aggregate support is empty, a full-compatible continuous coverage LP now supplies sparse reserve support to the candidate generator. This is candidate guidance only: it has no business objective and creates no UB.
3. Integer reserve completion incorrectly used continuous reserve RHS values. It now uses `required_reserve(..., "integer")`; this was the decisive correctness bug. The completed feasible support is passed as a nonbinding start to the exact restricted model.

Standalone repair stops after its first incumbent and reserves validation time for the independent checker and global recourse oracle. No UB is emitted before those checks pass.

## Final gate results

| Instance | Runtime | Guide | Level | Pair ratio | Canonical UB |
|---|---:|---|---:|---:|---:|
| tiny | 0.018 s | `mip_incumbent` | 0 | 0.5000 | 21000.0000 |
| tiny_concentration | 0.026 s | `mip_incumbent` | 0 | 0.5000 | 22000.0000 |
| XS01 | 0.145 s | `mip_incumbent` | 0 | 0.3333 | 33285.8752 |
| XS02 | 0.141 s | `mip_incumbent` | 0 | 0.4667 | 38345.5870 |
| XS03 | 0.169 s | `mip_incumbent` | 0 | 0.6667 | 45410.4471 |
| S01 | 1.273 s | `mip_incumbent` | 0 | 0.5000 | 28300.1761 |
| M01 | 4.708 s | `lp_fallback` | 0 | 0.2946 | 19290.7407 |
| L01 | 20.210 s | `static_fallback` + coverage support | 0 | 0.1399 | 24659.7628 |

## Gate evaluation

- Completeness: **PASS** — 8/8 runs completed.
- Safety: **PASS** — 8/8 exact feasible repair incumbents, zero exceptions, zero oracle inconsistencies.
- Checker and objective consistency: **PASS** for all eight incumbents.
- Runtime: **PASS** — every run is within its gate tolerance; L01 is below 22 seconds.
- Domain reduction: **PASS** — every ratio is below 1, L01 is strongly reduced, and median ratio is 0.5000.

No relative candidate-v1 quality threshold was applied, as required by Stage 04. The recorded values are first validated standalone incumbents and are development evidence.

## Verification and artifacts

- Focused final checks: **10 passed**.
- Full regression suite: **183 passed**.
- Candidate-v1 configuration and hash remain unchanged.

Artifacts under `validation/agfr_standalone/`:

- `raw_results.jsonl`
- `results.csv`
- `gate_report.json`
- `gate_report.md`
- `guide_diagnostics.csv`
- `candidate_domain.csv`
- `repair_attempts.csv`
- `model_size.csv`

## Stage boundary

Stage 04 ends with approval for BBC integration. No Stage-05 BBC integration has been implemented in this stage.

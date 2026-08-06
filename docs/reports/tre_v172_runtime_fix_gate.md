# TRE v1.7.2 runtime-correction gate

- Gate date: 2026-08-06
- Clean implementation commit: `6c7ed7dbe740199f9de8eb046676eaf75d8f7261`
- Branch: `research/tre-objective-normalization-v2`
- Problem protocol: `rolling-v4.6-objective-only-stability`
- Algorithm version: `lead-aware-aggregate-lp-residual-global-repair-v1.7.2`
- Result schema: `rolling-results-v16`
- Status: **passed; candidate v3 preflight rerun required**

## Failure being corrected

Preflight candidate v2 retained dense zero-valued MIP dictionaries and scanned
the complete `din` mapping within every period--block occupancy cell. On the
sequential seed-700 March confirmation, extraction/accounting took 121.83
seconds and independent validation took 212.37 seconds after Gurobi had already
returned an incumbent. Candidate v2 remains failed, and none of its partial
rows may be reused.

## Implemented correction

Version 1.7.2 makes no change to the mathematical model, lexicographic
priorities, normalization equations, business weights, feasible region,
execution, or recovery policy. It changes the implementation as follows:

1. Canonical occupancy accounting builds block-period loads from one scan each
   of locked inventory, actual inventory, and planned arrival flow.
2. Known physical model groups omit exact zero values during extraction, while
   a dense reference mode remains available for equivalence testing.
3. A positive shifted rolling plan is clipped deterministically to revised
   period forecasts and completed with matching reservation, shortage, support,
   height, cancellation, and block-share MIP-start values.
4. No artificial all-shortage start is submitted in the first cycle.
5. Within the unchanged 60-second online budget, measured sparse tails retain
   4.2 seconds for postprocessing and 2.0 seconds for solver return.

The last two values are internal allocations, not extra runtime allowances.

## Verification

The complete suite passes with 171 tests and 9 subtests. Added regressions
require exact dense/sparse equality of every canonical operations field,
single traversal of the planned-flow map, identical independent validation,
sparse/dense extraction equivalence, forecast-conserving clipped starts, and
absence of an artificial first-cycle shortage start.

The clean large-instance regression uses the unchanged frozen bundle
`pnc_yangshan_temporal_mar_observed_n4_seed700`, one thread, 1% MIP gap,
business weights, and 60 seconds per cycle. Its 2/2-row manifest is complete
and `all_ok=true`.

| Method | Max online (s) | Max audit (s) | Max extract (s) | Max validate (s) | Predicted shortage | Final unplaced |
|---|---:|---:|---:|---:|---:|---:|
| `core_start` | 56.00 | 56.53 | 1.85 | 0.18 | 0 | 0 |
| `full_bottleneck` | 55.26 | 55.62 | 1.17 | 0.15 | 0 | 0 |

Both rows complete all five effective decision cycles and all 4,718 realized
arrivals. Deadline misses, missing-incumbent failures, and independent
validation failures are zero. The maximum observed solver-return overrun is
0.49 seconds, below the retained 2.0-second guard.

## Artifact identity

- CSV SHA-256:
  `faf23807fdcbe6f9997368b65560e16254ff7f9754edbbf727038c35fdec10e7`
- Manifest SHA-256:
  `a93fcfcfc76022146db91c9d8aeef6240462303483a863061e13d189de45c118`
- Local root:
  `local_results/protocol_v3_tre_objective/development/v172_runtime_fix/`

These two rows are a development runtime regression, not publication results.
The complete 120-row preflight matrix must be rerun from a new clean candidate
v3 tag. Formal authorization remains false.

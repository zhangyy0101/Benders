# TRE v1.7.1 development gate

- Date: 2026-08-04
- Experiment phase: development only
- Seeds: 100, 101, 102
- Candidate commit: `ba3a7266c27c3ab7ff2fde35cf6397d9d8b89c9b`
- Candidate tag: `rolling-v4.6-objective-only-stability-development-v2`

## Development finding and correction

The first v1.7.0 checkpoint was stopped after three rows because the independent
validator rejected the two unrestricted time-limited solutions. Physical
feasibility and every operations component except occupancy balance passed.
The absolute utilization-deviation variables were epigraphs and could remain
above their physical value when the third-priority objective was unfinished.

Version 1.7.1 retains the mathematical objective but recomputes every operations
component from extracted `reservation` and `din` flows before incumbent
comparison and validation. The original incomplete checkpoint remains isolated
under `local_results/protocol_v3_tre_objective/development/32834c3` and is not
included below.

## Main development gate

The main gate used oracle-certified feasible and tight members of three scale
profiles. Every profile used one thread, a 1% MIP gap, the `business` operation
weight profile, and four internal methods: `core`, `core_start`,
`core_start_impact`, and `full_bottleneck`.

| Profile | Forecast setting | Cycle limit | Instances | Rows |
|---|---|---:|---:|---:|
| small | 10% booking add/cancel | 20 s | 6 | 24 |
| medium | 20% mixed | 20 s | 6 | 24 |
| large | 20% mixed | 60 s | 6 | 24 |

All 18 bundles have an optimal integer zero-shortage packing certificate. The
72-row matrix was complete: 72 successful rows, zero independent-validation
failures, zero deadline misses, zero no-incumbent failures, zero dirty rows,
and zero duplicate identities. The maximum cycle time was 3.95 seconds below
its applicable budget. All 72 stored normalized operations scores reproduced
the sum of their weighted components; the audit maximum error was
`5.55e-17`. No row enabled a hard stability budget.

The time-limited balance epigraph differed from physical accounting by as much
as 180.889, demonstrating that canonical flow accounting is necessary. These
slacks are diagnostics only; all accepted scores use the physical value.

| Mean by size and method | Online time (s) | Final unplaced | Stability | Operations score | Realized distance |
|---|---:|---:|---:|---:|---:|
| small / core | 34.95 | 0.00 | 402.33 | 0.2722 | 235,713 |
| small / full_bottleneck | 14.73 | 0.00 | 402.50 | 0.2402 | 189,533 |
| medium / core | 66.43 | 23.00 | 2,569.00 | 0.2302 | 1,231,563 |
| medium / full_bottleneck | 55.96 | 0.17 | 3,012.00 | 0.2383 | 1,149,467 |
| large / core | 250.81 | 0.00 | 3,885.33 | 0.2232 | 3,723,487 |
| large / full_bottleneck | 207.13 | 0.00 | 5,323.17 | 0.2314 | 3,401,047 |

Across all 18 paired instances, the candidate was faster than `core` in 18/18
and reduced mean online time by 24.79 seconds. Final unplaced quantity was
better/tied/worse in 3/15/0 pairs, with 137 fewer unplaced boxes in aggregate.
Realized distance was better in 16/18 pairs. The normalized operations score
split 9 wins and 9 losses, while stability cost was worse in 13/18 pairs. This
is an observed time-limited trade-off after removing the unsupported hard
stability budget; it is not evidence that stability ceased to be the second
lexicographic objective.

Against unrepaired `core_start_impact`, the candidate reduced final unplaced
quantity in 6 pairs and tied 12, with 429 fewer boxes in aggregate. It was
faster in 12/18 pairs but had a higher operations score in 12/18, showing the
cost of reliability repair rather than universal dominance.

## Mechanism and profile-isolation gates

The separate six-row nearby/global pressure panel completed successfully with
zero validation failures, deadline misses, or final unplaced boxes. Three rows
triggered bottleneck repair. The main gate additionally recorded one positive
residual-shortage transition to unrestricted global repair, so both recovery
paths were reached without pooling mechanism rows into performance claims.

A one-instance plumbing smoke completed separately for
`equal_weight_ablation`, `weak`, `business`, and `strong_distance`. Each output
and manifest recorded exactly one distinct profile identity. These rows verify
configuration isolation only and were not used to choose the primary weights.

## Artifact identities

- Main CSV SHA-256:
  `3afcd2e60f0e5e026981f8198f633e4738f7c762f9cbf4e795527848b58899bd`
- Main manifest SHA-256:
  `0d03490e858444dcfbcf9b1d444c1e844cb2657d7f5e8e9021bbd7e576390858`
- Exploratory summary SHA-256:
  `f80ebd96a99418bee4dd6f7532b7ba01f03250ef4f2444b3a62c5ce43aae9b80`
- Mechanism CSV SHA-256:
  `e8a8bdc3b8b5134d8ba9ae975af0d60dc9431ed22557d40c5fcbead77475a5a0`
- Mechanism manifest SHA-256:
  `887f7b84b265e4fe9a9349776910c1bcda10f194dd0de0b57a3e0ee3d1fa1657`

## Gate decision

The v1.7.1 development gate passes. This authorizes freezing a preflight
candidate, not a formal run. The primary empirical weights remain prespecified,
and `FORMAL_RESULT_AUTHORIZED` remains false.

## Post-gate reporting clarification

Result schema v16 was introduced after this sealed v15 development matrix to
record method-specific stability accounting and to include the complete
execution-recovery funnel in default summaries. It changes no optimization,
rolling execution, or physical recovery decision. The stored development CSV
already contains every recovery field, and the four internal rows correctly
used `epigraph_only`; therefore the development optimization was not rerun.

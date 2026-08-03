# TRE objective revision protocol

## Baseline preservation

The equal-weight objective is frozen at commit
`fd506b08c3b0c85d2c576ccf578bb3742d2f6ecc` under the annotated tag
`rolling-v4.4-objective-equal-weight-freeze-v1`. The tag is published to the
`origin` remote. Before the tag was created, the complete test suite passed
with 135 tests and 9 subtests.

The ignored local result roots `local_results/protocol_v2_pnc_yangshan`,
`local_results/formal`, and `local_results/preflight` are preserved in place.
Their non-destructive inventory is
`local_results/archive/objective_equal_weight_freeze_v1/inventory.json`. It
contains 1,139 files totaling 508,076,290 bytes, with aggregate SHA-256
`0af5eba1b82a8156ce35fe1b588c9cbe00bb58f68fbe3cff271eac8ba5a040a6`.
No revision run may resume from, overwrite, or merge with those artifacts.

## Planned objective revision

Development occurs on `research/tre-objective-normalization-v2`. The planned
version identities are:

- problem protocol: `rolling-v4.5-reachable-objective-scaling`;
- candidate algorithm: `lead-aware-aggregate-lp-screened-repair-v1.5.0`;
- result schema: `rolling-results-v12`;
- normalization: `reachable_snapshot_upper_bounds_v2`;
- new local root: `local_results/protocol_v3_tre_objective`.

The shortage--stability--operations lexicographic priorities remain unchanged.
Only the third-priority operations score is revised. Its scale dictionary must
still be calculated once from the unrestricted snapshot and reused by every
restricted and global stage.

The primary business profile is fixed before implementation as distance 0.40,
balance 0.30, concentration 0.20, and inbound/outbound conflict 0.10. The
prespecified sensitivity profiles are stored in
`docs/specs/formal_run_manifest_v3.json`; the old equal-weight profile is an
ablation, not a competing primary specification.

## Evaluation boundary

Formal outputs already exist for seeds 1000--1009 under objective version
1.4.7, including the 50-row central five-method matrix, the 140-row robustness
matrix, and synthetic formal panels. Under the existing repository rule that a
method revised after formal outcomes have been inspected requires a new
held-out set, those seeds may be reused only for historical or exploratory
paired re-evaluation of the objective change.

Before version 1.5.0 is authorized for a confirmatory formal run, register an
untouched seed set or an independent operational time window in the V3
manifest. Do not select the primary weight profile from any V3 result. All
profile definitions, normalization equations, evaluation panels, and stopping
rules must be frozen in a clean tagged commit before the new confirmatory set
is opened.

## Gates before a new formal tag

1. Implement and unit-test the reachable scale equations and weight-profile
   plumbing without changing the first two objective priorities.
2. Run development and preflight cases only; record raw, normalized, scale,
   weight, and weighted-contribution fields for every operations component.
3. Confirm that every stage receives the same unrestricted scale dictionary.
4. Confirm that the business and sensitivity profiles do not mix output roots
   or resume identities.
5. Select and register a new untouched confirmatory set.
6. Commit a clean worktree, pass the complete test suite, freeze the V3
   manifest, and create a new annotated formal tag.

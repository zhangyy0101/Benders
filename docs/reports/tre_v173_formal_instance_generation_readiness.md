# TRE v1.7.3 formal-instance generation readiness

## Decision

The code and experiment design are frozen for generation of the new
confirmatory instances. This authorization does **not** mean that an instance
has been generated or a formal outcome has been observed. Actual generation
still requires a clean checkout at the exact annotated tag
`rolling-v4.6-objective-only-stability-formal-input-rc1` and both explicit
flags `--generate --confirm-open-formal-seeds`.

The current confirmatory seeds are `2000--2009`. A repository and local-result
collision audit found no corresponding seed field, instance identifier or
filename before registration. Seeds `1000--1009` were already opened under the
historical objective and are excluded from current confirmatory evidence.

## Frozen identities and evidence gate

- Problem protocol: `rolling-v4.6-objective-only-stability`.
- Candidate: `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`.
- Result schema: `rolling-results-v16`.
- Normalization: `reachable_snapshot_upper_bounds_v2`.
- Primary operation weights: distance 0.40, balance 0.30, concentration 0.20,
  inbound/outbound conflict 0.10.
- Controlled preflight: 120/120 valid rows, five methods × 24 rows, with zero
  deadline, no-incumbent, validation or final-unplaced failures.
- Execution: one process and one solver thread, sequential batches, exclusive
  host, frozen 1% MIP gap and bundle-level cycle budgets.

The controlled-preflight CSV and manifest hashes, source-design hashes,
untouched-seed registration and generation paths are embedded in the V3 JSON
specifications and are revalidated by the preparation entry point.

The complete repository suite passed before the formal-input freeze with 184
tests and 16 subtests. All JSON specifications parsed successfully, all changed
Python entry points compiled, and `git diff --check` found no patch errors.

## Frozen matrix

| Evidence family | Expected rows |
|---|---:|
| PNC--Yangshan central five-method comparison | 50 |
| PNC--Yangshan temporal/volume/yard robustness | 140 |
| Operation-weight sensitivity | 60 |
| DRA-RPM parameter sensitivity | 60 |
| Fully synthetic performance panels | 680 |
| Fully synthetic repair-mechanism diagnostics | 60 |
| Total | 1,050 |

The exact 12-batch order is in
`docs/specs/tre_v3_formal_execution_plan.json`. The business-weight reference
and frozen DRA-RPM reference are reused from the central main batch; they are
not rerun merely to inflate the sample. The matrix deliberately omits an
additional time-budget sensitivity grid because the scale panel already fixes
20/60/120-second budgets and the main claim does not require a second post-hoc
time family.

## Statistical and failure policy

The independent replication unit is one seed within one prespecified scenario
cell. Confidence intervals and Wilcoxon tests are computed within that cell;
cells that share a seed are never pooled as independent replicates. Holm
correction is applied within each cell and prespecified metric family.

All requested rows must remain auditable. Deadline/no-incumbent failures count
against the method; validation failures remain in failure accounting but are
excluded from quality summaries. A quality pair requires two valid rows.
Selective reruns are prohibited. Environmental contamination invalidates the
whole affected batch, which is quarantined and restarted from zero.

## Safe entry point

The non-generating final gate is:

```powershell
python scripts/prepare_tre_v3_formal_instances.py --check-only
```

It verifies the clean Git identity and exact tag, 22 frozen PNC/Yangshan source
files, current specifications, 120-row controlled-preflight hashes, absent
confirmatory output root, 13 guarded generation commands and the expected
310 + 740 result-row design. The default command is also non-generating.

Only after that gate passes may the user deliberately open the registered
seeds with:

```powershell
python scripts/prepare_tre_v3_formal_instances.py `
  --generate --confirm-open-formal-seeds
```

No generation command is part of this readiness work.

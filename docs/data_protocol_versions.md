# Data protocol version registry

This registry separates historical experiment evidence from the formal
PNC--Yangshan redesign. Results from different protocols must not be pooled or
written to the same output directory.

## V1: Sinsundae capacity-calibrated semi-synthetic data

- Status: historical development evidence
- Source terminal: Sinsundae Container Terminal
- Public source periods: March, July, and November 2025
- Demand protocol: `portmis-demand-v1`
- Code baseline: `d4c61438ff6c4d1749cfae5eb94bc1ff253c9617`
- Git tag: `pre-pnc-yangshan-v1`
- Existing incomplete formal public matrix: 15 of 210 expected rows

The incomplete V1 public matrix must not be resumed or reported as a completed
formal experiment. Existing V1 files are retained locally and must not be
overwritten by V2 runs. Unchanged, hash-verified fully synthetic scale and
pressure instances may be reviewed separately for reuse.

## V2: PNC--Yangshan data-driven semi-synthetic data

- Status: development; not yet frozen for formal experiments
- Development branch: `research/pnc-yangshan-formal-v2`
- Source terminal: PNC / Busan New Port Pier 2
- Candidate primary source period: May 2026
- Candidate scale windows:
  - 2026-05-08 through 2026-05-10
  - 2026-05-14 through 2026-05-20
  - 2026-05-21 through 2026-05-31
- Vessel skeleton: observed PORT-MIS calls
- Box attributes: Yangshan-calibrated `(POD, 20/40 ft, height)` groups
- Yard: model-compatible virtual yard calibrated from Yangshan snapshots

V2 changes the data protocol only. The mathematical model, supported box
attributes, constraints, candidate algorithm, external baselines, evaluator,
and validation boundary remain frozen unless a later protocol revision
explicitly states otherwise.

## Local data and result isolation

The raw `data_analysis/` directory and generated `local_results/` directory are
local-only and ignored by Git. Raw terminal data must be represented in the
repository by audited schemas, provenance records, and cryptographic file
hashes rather than by committing the source files.

New V2 artifacts must use a separate root:

```text
local_results/protocol_v2_pnc_yangshan/
```

V1 artifacts remain under their existing locations until a non-destructive
archive inventory has been generated. No V1 file may be deleted, moved, or
renamed merely to prepare V2.

# TRE v1.7.3 preflight candidate v5 pre-run audit

The initial audit completed preparation before any candidate-v5 solver row was
started. Candidate v4 was superseded with zero result rows because a legacy
candidate-v3 resume process was discovered after the v4 tag. That process was
terminated, and candidate v3 remains a permanently failed diagnostic attempt.
The stable candidate-v3 checkpoint contains 60 rows and three same-mechanism
deadline failures. All three pass v1.7.3 directional regression; the closest
case also passes an immediate repeat at 59.388 and 56.495 seconds respectively,
with zero deadline misses, validation failures, and final unplaced quantity.

After the candidate-v5 tag was published, delayed background commands from a
concurrent interactive session started two uncontrolled local checkpoints.
They were not launched from the declared exclusive foreground protocol. The
first contains 3 of 120 rows and the second contains 4 of 120 rows; both have
`complete=false` and `all_ok=false`. Their overlapping first instance records
the same `core_start` and `full_bottleneck` deadline misses, while the completed
literature-baseline rows are feasible. The directories are retained under
`local_results/protocol_v3_tre_objective/preflight/quarantine/` as
`preflight_candidate_v5_aborted_20260806_135001` and
`preflight_candidate_v5_aborted_20260806_135133`. These failures remain part of
the diagnostic audit, but the checkpoints must not be resumed, merged, or
reported as a controlled preflight because process ownership and exclusive-host
conditions were violated before the first row.

## Frozen implementation and execution policy

- Algorithm implementation commit:
  `bdd4f5331c3aea7d33bdcca57e3dd727908acfbb`.
- Immutable preflight orchestration commit:
  `74b27f634a38f3282c99d2328a75e2e69b5d9fe6`.
- Algorithm version:
  `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`.
- Orchestration protocol: `immutable-indexed-publication-v2`.
- Frozen tag:
  `rolling-v4.6-objective-only-stability-preflight-candidate-v5`.
- Formal authorization remains false.

The runner now stops before solving unless the Git tree is clean, all inputs
come from preflight-phase immutable indexes, bundle time budgets are used
without override, threads equal 1, MIP gap equals 1%, the main five-method and
frozen profile identities match, and a fresh output path is selected. Existing
artifacts can only be continued through explicit `--resume`, whose metadata and
requested-matrix equality checks remain mandatory.

## Frozen input and matrix audit

All three index hashes match the manifest. They contain 24 unique bundles over
seeds 700, 701, and 702. Every bundle SHA-256 and embedded case SHA-256 matches
its index. All 24 integer packing certificates prove optimum zero minimum
shortage. Every bundle carries the same 60-second per-cycle budget and the
`preflight` phase. Five methods yield exactly 120 requested rows:
`core_start`, `full_bottleneck`, `kp_dos`, `kp_sg`, and `dra_rpm`.

The two uncontrolled candidate-v5 roots have been moved intact to quarantine.
The controlled retry output root
`preflight_candidate_v5_controlled_retry1` does not exist at audit time. It
must be created only by a new run without `--resume`. The empty candidate-v4
log directory contains no CSV, manifest, or solver row and will not be reused.

## Environment and verification

- Python 3.12.0;
- gurobipy 13.0.0 with the licensed host environment verified by the complete
  Gurobi-dependent test suite;
- approximately 236.1 GB free on the workspace drive at the controlled-retry
  readiness audit;
- no Python experiment or solver process active;
- 175 tests and 16 subtests pass;
- formal input generation and execution remain closed.

The controlled preflight must run sequentially from a fresh detached checkout
of the clean candidate-v5 tag into the new
`preflight_candidate_v5_controlled_retry1` result root. It must use a single
managed foreground process, no Task Scheduler entry, no launcher script, and
no `--resume`. The local and `origin` annotated tag objects both resolve to
`e7651b3801836ad15c2d05b2eecb92d4304c2c6a`. The matrix is not to be launched
until the user explicitly confirms.

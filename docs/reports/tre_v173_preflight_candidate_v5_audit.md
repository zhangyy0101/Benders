# TRE v1.7.3 preflight candidate v5 pre-run audit

This audit completes preparation only. No candidate-v5 solver row has been
started. Candidate v4 is superseded with zero result rows because a legacy
candidate-v3 resume process was discovered after the v4 tag. That process was
terminated, and candidate v3 remains a permanently failed diagnostic attempt.
The stable candidate-v3 checkpoint contains 60 rows and three same-mechanism
deadline failures. All three pass v1.7.3 directional regression; the closest
case also passes an immediate repeat at 59.388 and 56.495 seconds respectively,
with zero deadline misses, validation failures, and final unplaced quantity.

## Frozen implementation and execution policy

- Algorithm implementation commit:
  `bdd4f5331c3aea7d33bdcca57e3dd727908acfbb`.
- Immutable preflight orchestration commit:
  `74b27f634a38f3282c99d2328a75e2e69b5d9fe6`.
- Algorithm version:
  `lead-aware-aggregate-lp-residual-global-repair-v1.7.3`.
- Orchestration protocol: `immutable-indexed-publication-v2`.
- Planned tag:
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

The candidate-v5 result root does not exist at audit time. The empty
candidate-v4 log directory contains no CSV, manifest, or solver row and will
not be reused.

## Environment and verification

- Python 3.12.0;
- gurobipy 13.0.0 with the licensed host environment verified by the complete
  Gurobi-dependent test suite;
- approximately 253.7 GB free on the workspace drive at audit time;
- no Python experiment or solver process active;
- 175 tests and 16 subtests pass;
- formal input generation and execution remain closed.

The new preflight must run sequentially from the clean candidate-v5 tag into
`local_results/protocol_v3_tre_objective/preflight/preflight_candidate_v5`.
Preparation is complete only after the branch and tag are present on `origin`;
the matrix is not to be launched until the user explicitly confirms.

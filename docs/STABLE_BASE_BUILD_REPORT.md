# Stable Candidate-v1 Base Build Report

Build date: 2026-07-14

## Provenance

- Branch: `cleanup/stable-candidate-v1`
- Base commit: `2f34af5b9addd08d5070500074624bac616f76e8`
- Base subject: `clean candidate v1 entrypoints before v2 development`
- Candidate-v2 failed-route history: `archive/candidate-v2-lb-screened-out`

The branch was created directly from the P5 completion commit. It was not constructed by reversing changes from the P6B head.

## Required stable content

Verified present:

- candidate experiment runner;
- candidate-v1 smoke runner;
- configuration-driven `main.py`;
- candidate-v1 immutability regression tests;
- P5 cleanup report and evidence hierarchy;
- candidate decision files and consistent Pilot2.1 status.

Both supported entrypoints default to `algorithm-candidate-v1`; the experiment runner defaults to `benchmarks/paper_exp_v1_pilot21`. Entrypoint overrides are labeled `development_override` and receive a new hash. Public-data documentation permits development/calibration work while prohibiting final holdout execution.

## Candidate-v1 invariant

```text
configuration_name = algorithm-candidate-v1
configuration_hash = fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce
aggregate_recourse_lb = true
analytic_recourse_lb = false
root_prepass = false
warm_start = false
alns = false
valid_inequalities = false
node_cuts = false
cut_strategy = standard
phase_shares = {root:0,warm:0,alns:0,main:1}
```

The invariant check passed without modifying the configuration payload.

## Excluded P6A/P6B content

The active tree contains no registered V2A/V2B/V2C configuration, POD-size aggregate implementation, candidate-v2 fast-screen script/results, candidate-v2 exact results, or P6A implementation report. One `pod_size` string remains in a label-resolution compatibility unit test only; it is not active implementation or configuration.

## Stage 02 validation

- Python compilation: PASS
- Targeted tests: PASS (`10 passed`)
- Candidate-v1 smoke: PASS (`3 runs`)
- Candidate hash reported by smoke: `fc505c53a75c375b8f7c4532830c577221827c1c820a10cc688686234cac8bce`
- XS01 aggregate-LB switch match: PASS
- XS01 exact objective match: PASS

Stage 02 does not update `main` and does not delete any branch.

# AGFR–BBC Integration Report (Stage 05)

## Outcome

Stage 05 is implemented as a development configuration named
`candidate-v2-agfr-development`. The frozen `algorithm-candidate-v1` payload
and hash remain unchanged.

The enabled sequence is:

```text
AGFR -> main BBC
```

AGFR receives 8% of the total budget subject to the 2–20 second bounds. Any
unused time is returned through the shared global deadline; main BBC receives
the actual remaining time.

## Integration behavior

- AGFR solutions are independently checked and evaluated before BBC use.
- Global recourse is solved again, its cache is seeded, and a tight initial
  optimality cut is installed.
- `x`, `alloc_boxes`, and `eta` starts plus an objective cutoff are supplied to
  the master.
- AGFR is labeled `repair/agfr_incumbent`, never warm or ALNS.
- Ordinary AGFR failure falls through to main BBC.
- Final UB selection includes AGFR and main BBC; the reported LB remains the
  main BBC bound.
- Experiment output contains a top-level `repair` object and separate `repair`
  and `guide` timings.

## Verification

- Full regression: `190 passed`.
- Stage 05 focused tests: `7 passed` across the six requested test modules.
- Tiny v2 smoke: successful.
  - repair status: `SOLUTION_LIMIT`
  - BBC start source: `agfr`
  - seeded recourse cache entries: `1`
  - initial cut tightness: `0.0`
  - final solution source: `main_bbc`
- Candidate CLI shows only `algorithm-candidate-v1` and
  `candidate-v2-agfr-development` by default; historical C0–C8 configurations
  remain opt-in.

No performance screen was run and candidate-v2 remains a development
candidate.

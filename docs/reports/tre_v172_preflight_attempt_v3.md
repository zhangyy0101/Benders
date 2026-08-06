# TRE v1.7.2 preflight attempt candidate v3

Candidate v3 is permanently failed at the strict online-runtime gate. It was
started sequentially from frozen commit
`e4942cf653b9be6b6191257a4fb3c05b4b0b4ebb` and stopped after the repeated
failure mechanism was identified. Its artifacts are diagnostic only and must
not be resumed or combined with a later candidate.

The final retained checkpoint contains 60 of 120 requested rows: 12 for each
of the five methods. Legacy orphan resume processes extended the checkpoint
after the first stop; they were identified and terminated before any new
candidate run began. Three
`full_bottleneck` rows failed with
`online_decision_time_limit_exceeded`; there were no validation failures.

| Instance | Variables | Old maximum cycle (s) | Final unplaced |
| --- | ---: | ---: | ---: |
| `pnc_yangshan_volume_low_low_n4_seed700` | 561,020 | 60.687 | 0 |
| `pnc_yangshan_yard_observed_observed_n4_seed700` | 686,879 | 65.594 | 0 |
| `pnc_yangshan_volume_baseline_observed_n4_seed701` | 681,347 | 63.654 | 0 |

Both failures followed positive bottleneck-stage residual shortage into an
unrestricted global repair. Under the 60-second budget, v1.7.2 reserved only
9 seconds for this repair and allowed it to start with as little as 0.05
seconds remaining. Gurobi's solver limit can bound optimization, but Python-side
construction of these 561k--687k-variable models is not interruptible by that
limit. The controller therefore admitted a stage whose build could not finish
inside the remaining online window.

This is an internal stage-allocation defect rather than evidence that the
common 60-second budget is intrinsically too small. On the first failed bundle,
`core_start` used the same common budget and comparable maximum model size but
completed all five solved cycles with a maximum online decision time of 55.261
seconds. The completed adapted literature baselines were also much faster and
processed the same effective rolling cycles and arrivals, so their speed does
not indicate skipped evaluation.

The retained CSV SHA-256 is
`9bf01b2b303df38f15c6ca174c4608f13754cc656131817843f713ac524b2392`;
the manifest SHA-256 is
`47e5298b345334a5bb626c9e02f3ade24ebe9329f8e69d07e3e078faad708fef`.
`complete=false`, `all_ok=false`, and formal authorization remains false.

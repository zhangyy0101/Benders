# PNC--Yangshan v1.4.4 candidate preflight

> Superseded diagnostic. These rows were launched in pairs on one workstation.
> Competing Python model construction and memory pressure consumed the common
> wall-clock budget unevenly. They are retained only as the evidence that
> resource-unisolated parallel execution is invalid for this preflight. The
> corrected sequential v1.4.7 result is reported in
> `pnc_yangshan_v147_candidate_preflight.md`.

Eight frozen semi-synthetic preflight bundles were run with seed 700, one
solver thread, and a 60-second online-decision budget per cycle. The scale
bundles were excluded because they are development diagnostics rather than
members of the semi-synthetic preflight index.

| Scenario | Completed | Arrivals | Pre-recovery shortfall | Final unplaced | Revision rate | Peak utilization | Total online time (s) | Max cycle (s) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| temporal March | yes | 4,718 | 1 | 0 | 50.38% | 82.35% | 116.22 | 46.97 |
| temporal April | yes | 4,365 | 0 | 0 | 0.06% | 68.45% | 86.31 | 47.11 |
| temporal June | no, 2 cycles | 235 | 0 | 0 (partial) | 0.00% | 54.18% | 91.50 | 46.69 |
| volume baseline | yes | 4,347 | 4 | 0 | 0.00% | 89.20% | 131.09 | 46.07 |
| volume low | yes | 3,497 | 0 | 0 | 0.02% | 67.09% | 148.06 | 46.67 |
| volume high | yes | 5,269 | 0 | 0 | 0.01% | 69.78% | 131.84 | 46.82 |
| yard observed | yes | 4,347 | 915 | 0 | 0.32% | 95.33% | 146.71 | 47.11 |
| yard high pressure | yes | 4,347 | 0 | 0 | 50.24% | 78.95% | 120.81 | 47.13 |

Seven bundles completed and one failed. The June temporal bundle reached a
no-incumbent deadline in its second global-core cycle, so its reported
execution metrics are partial and cannot be interpreted as a complete result.
The observed-yard bundle required 915 physical-capacity recovery placements
and had mean predicted shortage 1,152.6. March and the high-pressure yard
bundle completed with zero final unplaced boxes but revised about half of the
previous reservation basis.

The candidate therefore does not pass the algorithm-freeze gate. The failure
is not a common cycle-wall overrun: every completed cycle stayed below 47.14
seconds. The unresolved gates are global-core incumbent reliability, excessive
reservation-domain recovery on the observed-yard calibration, and
high-revision paths in two scenarios. Formal seeds must remain unopened and
the external-baseline matrix must not yet be treated as a formal comparison.

The retained raw rows are under
`local_results/protocol_v2_pnc_yangshan/preflight_runs/v144_remaining/`; the
volume-baseline row is
`semisynthetic_baseline_candidate_v144_stable_repair_t60.csv`.

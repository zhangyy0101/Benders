# PNC--Yangshan algorithm preflight

The semi-synthetic paper matrix was reduced before algorithm execution.
Synthetic data retain responsibility for computational scale and controlled
stress. The semi-synthetic index contains eight unique bundles supporting
temporal, demand-volume, and yard-calibration robustness; the earlier 2/4/6
call scale bundles remain development diagnostics only.

## Representative paired run

The May observed-volume, capacity-relief-yard bundle was run through the two
frozen optimization configurations and all three external baselines. Every
method consumed the same instance and case hashes, seed 700, and a common
60-second per-cycle preflight budget under algorithm version 1.4.1.

| Method | Completed | Max cycle time (s) | Realized unplaced | Stability cost | Revision rate | Peak block utilization |
|---|---:|---:|---:|---:|---:|---:|
| `core_start` | no (2 cycles) | 46.36 | 156 (partial run) | 0 (partial run) | 0 (partial run) | 53.01% |
| `full_bottleneck` | yes | 59.75 | 28 (0.644%) | 11,867 | 36.89% | 73.79% |
| `kp_dos` | yes | 2.03 | 0 | 16,668 | 54.00% | 97.28% |
| `kp_sg` | yes | 31.03 | 0 | 21,451 | 70.11% | 91.15% |
| `dra_rpm` | yes | 50.71 | 0 | 10,496 | 12.63% | 97.09% |

`core_start` reached a no-incumbent deadline after two cycles, so its
unplaced and cost values are incomplete and cannot be ranked against the four
completed methods. The candidate was the only optimization configuration to
complete all effective cycles within the common budget. All three external
baselines also completed.

The initial data-instance gate did not pass. Investigation showed that the
bottleneck selector repeatedly scanned every inventory and planned-flow entry
for every bay-period and did not charge this preparation against its nominal
one-second selector budget. The equivalent indexed implementation
(`sparse-indexed-v4`, algorithm version 1.4.1) preserves the selector model but
indexes inventory by bay, groups selector variables before constraint
construction, caches compatible group-block bays, and applies the time budget
to preparation, model construction, and optimization together.

On the same bundle and seed, the candidate completed all five effective
cycles. Total bottleneck-selection time fell from 113.73 seconds to about
1.78 seconds. Realized unplaced demand fell from 1,441 boxes (33.15%) in the
old 90-second implementation to 15--28 boxes (0.345%--0.644%) in repeated new
60-second runs. This small variation reflects wall-clock-limited solver paths,
not a changed instance.

Against the completed external baselines, the candidate does not win the
lexicographically primary unplaced-box metric (28 versus 0). It does improve
stability, revision rate, conflict, fragmentation, and yard balance relative
to both KP baselines. DRA-RPM has better stability, revision, and conflict,
whereas the candidate has substantially lower peak block utilization and
slightly lower travel distance. These are preflight observations from one
bundle and one seed, not formal statistical claims.

## Physical-capacity recovery correction

The execution fallback originally searched only bays with a positive
same-ship/same-group reservation. Consequently, a realized box could be
reported unplaced even while another compatible OF bay had true free
capacity. Version 1.4.2 adds a final deterministic physical-capacity recovery
over all compatible OF bays. It retains size, height, release, and capacity
constraints and reduces any future reservation displaced by the recovered
placement.

On the same May bundle, seed 700, and 60-second cycle budget, all 4,347
realized export boxes were placed and realized unplaced demand was zero.
Physical recovery placed 755 boxes outside their original reservation domain
and displaced 333 units of future reservation. Every period passed the
independent execution-state validator. Because this correction changes the
common execution policy, all methods must be rerun under protocol
`rolling-v4.4-physical-capacity-recovery` before the next paired comparison.

Version 1.4.3 subsequently removed inventory variables that were exact
reporting transforms of the arrival variables and replaced repeated
period-by-period cumulative-flow bounds with the equivalent bay-level
reservation-flow equality. This does not change the feasible set or objective.
On the same representative run, total online decision time fell from 219.79 to
143.92 seconds (34.5%), maximum cycle time from 59.13 to 46.82 seconds,
preprocessing/model-construction time from 150.39 to 66.79 seconds, maximum
variables from 1,438,567 to 681,463, and maximum constraints from 1,847,351 to
344,253. Realized unplaced demand remained zero.

Repeated identical-snapshot diagnostics subsequently confirmed a
runtime-path defect: mechanically dividing the remaining recovery time
between bottleneck and global repair produced final predicted shortages of
551, 446, and 2,734. The global model returned no new incumbent in its short
window. Version 1.4.4 assigns the remaining recovery window to the selected
bottleneck model and enters global recovery only when bottleneck selection or
solution fails. Three fixed-snapshot repetitions then followed the same stage
path and avoided the 2,734-box failure. Two complete rolling repetitions used
only 4 and 6 physical-capacity recovery placements and ended with zero
unplaced boxes.

The original large failure is therefore not evidence that the semi-synthetic
data are unusable. It was primarily an implementation defect. Version 1.4.7
subsequently passed all 24 declared seed-700--702 preflight runs: every
arrival was placed, 31 of 106,499 arrivals required physical recovery, and
the maximum cycle time was 46.46 seconds. The candidate is therefore frozen
and authorized for formal comparison, subject to the fixed formal manifest
and the prohibition on tuning after formal seeds are opened.

## Required resolution

The complete three-seed preflight gate has now been run. A proportional
subterminal sampling rule is not required and must not be introduced merely
to improve the candidate's result. If later data-integrity checks reveal
material runtime or
shortage failures, data resolution can be reconsidered as a separately
declared robustness design rather than an algorithm fix.

## Complete five-method gate

The frozen candidate, `core_start`, and all three external baselines were
subsequently run on the same 24 immutable seed-700--702 instances. The merged
matrix contains 120 rows. All rows completed, final unplaced demand was zero,
all execution validators passed, and no cycle exceeded the common 60-second
limit. The maximum observed cycle time was 46.75 seconds.

The candidate reduced aggregate decision time by 17.9%, mean travel distance
by 13.0%, and mean conflict by 33.7% relative to `core_start`, but
`core_start` used less physical recovery and had better fragmentation, peak
utilization, stability, and revision measures. The external baselines were
much faster; the candidate instead showed its main advantage in conflict,
fragmentation, yard balance, stability, and revision quality. Thus the gate
authorizes a formal comparison without asserting universal dominance.

Full results and reproducibility identifiers are recorded in
`docs/reports/pnc_yangshan_v147_v11_five_method_preflight.md`.

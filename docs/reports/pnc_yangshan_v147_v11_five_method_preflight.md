# PNC--Yangshan five-method, three-seed preflight

The complete preflight comparison contains the eight frozen semi-synthetic
profiles for seeds 700, 701, and 702. Each of the 24 immutable instances was
run with candidate `full_bottleneck`, internal comparator `core_start`, and
the three adapted external baselines `kp_dos`, `kp_sg`, and `dra_rpm`.

All 120 rows passed. Every method placed every realized export box; there
were no execution-state validation failures, online-decision deadline misses,
or missing method-instance pairs. The maximum single-cycle decision time was
46.75 seconds under the common 60-second preflight limit.

| Method | Runs passed | Final unplaced | Total decision time (s) | Mean decision time (s) | Physical recovery | Mean distance (million) | Mean conflict | Mean bays / ship-POD | Mean peak utilization | Mean stability cost | Mean revision rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `full_bottleneck` | 24/24 | 0 | 2,996.5 | 124.85 | 31 | 8.74 | 176.55 | 11.16 | 77.24% | 3,168.8 | 0.2500% |
| `core_start` | 24/24 | 0 | 3,648.9 | 152.04 | 4 | 10.05 | 266.48 | 10.63 | 68.60% | 2,989.8 | 0.0104% |
| `kp_dos` | 24/24 | 0 | 53.1 | 2.21 | 9 | 4.03 | 314.26 | 21.73 | 95.39% | 15,654.7 | 44.2421% |
| `kp_sg` | 24/24 | 0 | 633.4 | 26.39 | 9 | 4.10 | 395.17 | 21.35 | 91.71% | 21,049.3 | 65.1614% |
| `dra_rpm` | 24/24 | 0 | 428.9 | 17.87 | 5 | 8.56 | 329.34 | 18.06 | 93.60% | 13,780.0 | 35.3783% |

Against `core_start`, the candidate was faster on 20 of 24 paired
instances, reduced aggregate decision time by 17.9%, reduced mean realized
distance by 13.0%, and reduced mean conflict by 33.7%. It won the paired
distance comparison 17--7 and conflict comparison 19--5. `core_start`,
however, required less physical recovery and had better fragmentation, peak
utilization, stability, and revision measures. The candidate therefore has a
clear efficiency/conflict advantage over `core_start`, but not a universal
quality advantage.

The external baselines are much faster and the two KP methods achieve lower
travel distance. The candidate's distinct advantage is solution structure:
it beats each external baseline on conflict in 21 of 24 pairs, beats all
three on bays per ship-POD in 24 of 24 pairs, and overwhelmingly improves
peak utilization, stability, and revision rate. These results support
continuing to formal experiments; they do not support claiming that the
candidate dominates every comparator on every metric.

The common physical-capacity recovery rule was active for all five methods.
Across 120 method-runs it placed 58 boxes, including 31 for the candidate.
This metric must remain separately reported in formal experiments even
though final unplaced demand is zero.

## Reproducibility record

- Candidate version:
  `lead-aware-aggregate-lp-screened-repair-v1.4.7`
- External-baseline protocol:
  `adapted-literature-baselines-v1.1-sparse-cached`
- Rows: 120
- Immutable instances: 24
- Merged CSV SHA-256:
  `7ac1ecc7a621cb1136acfdf3bc9dcd308722034fd339ad9016f417259104af01`
- Machine-readable directory:
  `local_results/protocol_v2_pnc_yangshan/preflight_runs/v147_v11_five_method_three_seed/`

The merge audit rechecked the instance-bundle and case hashes against the
three frozen seed indexes. Pre-optimization external-baseline rows and
interrupted diagnostic rows were explicitly excluded.

This is a preflight result, not part of the formal paper sample. It closes the
five-method interface and feasibility gate. Formal seeds remain unopened
until the clean-code freeze and formal run manifest are fixed.

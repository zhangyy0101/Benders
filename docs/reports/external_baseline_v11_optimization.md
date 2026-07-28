# External baseline v1.1 implementation optimization

The PNC--Yangshan preflight exposed repeated scans in `kp_sg` and `dra_rpm`
on a 40-area, 1,519-bay rolling instance. The implementation was changed only
to cache immutable jobs, inventory indexes, temporal support, compatibility,
distance means, and DRA block-level future capacity.

On the seed-700 May baseline bundle:

| Method | Before total online (s) | After total online (s) | Before max cycle (s) | After max cycle (s) | After final unplaced | After physical recovery |
|---|---:|---:|---:|---:|---:|---:|
| `kp_sg` | 99.4 | 33.75 | about 31 | 12.37 | 0 | 0 |
| `dra_rpm` | 154.4 | 22.65 | about 50 | 8.47 | 0 | 0 |

On the seed-700 high-pressure-yard bundle, optimized `dra_rpm` used 22.27
seconds in total, reached a maximum cycle time of 8.62 seconds, and reduced
physical recovery from the earlier time-truncated 220 boxes to zero. This is
not an added recovery or candidate rule: the unchanged DRA allocation now
finishes inside its existing time budget.

The external-baseline unit suite passes, including cached-versus-direct DRA
reward equivalence. A pre-change module comparison on a nonbinding fixed
snapshot reproduced identical `din`, reservation, and shortage dictionaries
for `kp_dos`, `kp_sg`, and `dra_rpm`. The full repository suite reports 121
tests and 9 subtests passing.

The interrupted pre-optimization interface results are diagnostic only. The
complete seed-700--702 external-baseline preflight must restart from seed 700
under protocol `adapted-literature-baselines-v1.1-sparse-cached`.

The seed-700 restart has now completed all eight scenarios:

| Method | Rows passed | Total online time (s) | Maximum cycle (s) | Final unplaced | Physical recovery |
|---|---:|---:|---:|---:|---:|
| `kp_dos` | 8/8 | 22.30 | 1.20 | 0 | 3 |
| `kp_sg` | 8/8 | 267.90 | 12.86 | 0 | 3 |
| `dra_rpm` | 8/8 | 185.07 | 9.65 | 0 | 1 |

All 24 rows use the v1.1 protocol, pass independent validation, and have no
online deadline miss. The three methods together require seven physical
recovery placements. The earlier seed-700 v1 diagnostic used 542, of which
535 belonged to time-truncated DRA-RPM runs; it remains optimization
diagnostic evidence and is not mixed with the restarted matrix.

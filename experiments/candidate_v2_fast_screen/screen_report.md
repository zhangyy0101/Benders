# Candidate-v2 fast strengthening screen

Status: **COMPLETE**

- Runs: 12/12
- Runtime: 1454.27 seconds
- Selected for P7: none

## Per-run results

| Instance | Config | UB | LB | Gap | Target distance |
|---|---|---:|---:|---:|---:|
| S01 | algorithm-candidate-v1 | 20378.393655283995 | 18644.27452822827 | 0.08509596764051508 | 0.03509596764051508 |
| S01 | V2A_valid | 20095.525597401254 | 18703.895948686593 | 0.06925072160812883 | 0.019250721608128823 |
| S01 | V2B_pod_size_aggregate | 20420.21548766463 | 18724.64945827806 | 0.08303369915027688 | 0.033033699150276874 |
| S01 | V2C_pod_size_aggregate_valid | 19837.1657388925 | 18959.250439822066 | 0.044256085300996666 | 0 |
| M01 | algorithm-candidate-v1 | 15087.37787699342 | 13634.926172373172 | 0.09626932635094103 | 0.016269326350941027 |
| M01 | V2A_valid | 14983.109711490992 | 13652.375117020156 | 0.08881564775904004 | 0.008815647759040035 |
| M01 | V2B_pod_size_aggregate | 15224.537738618023 | 13679.433806197025 | 0.10148774031422589 | 0.021487740314225887 |
| M01 | V2C_pod_size_aggregate_valid | 15147.98778447387 | 13695.396325553767 | 0.09589336086004471 | 0.01589336086004471 |
| L01 | algorithm-candidate-v1 | 16507.651224003 | 13963.88465510708 | 0.1540962148023304 | 0.0540962148023304 |
| L01 | V2A_valid | 16277.772574931598 | 13968.399995363354 | 0.14187276354534942 | 0.04187276354534941 |
| L01 | V2B_pod_size_aggregate | None | None | None | None |
| L01 | V2C_pod_size_aggregate_valid | None | None | None | None |

## Decisions

- V2A_valid: drop — model-build overhead threshold exceeded
- V2B_pod_size_aggregate: drop — feasible rate below 3/3; gap improves on fewer than 2/3 instances; L01 strengthening threshold not met; model-build overhead threshold exceeded; safety gate failed
- V2C_pod_size_aggregate_valid: drop — feasible rate below 3/3; L01 strengthening threshold not met; safety gate failed

## Component findings

- Valid inequalities: V2A improved gap on 3/3 instances and met the L01 gap threshold, but failed the per-instance model-build overhead rule.
- POD–size aggregate: V2B improved gap on only S01, worsened M01 gap, and found no L01 incumbent.
- Combined V2C: V2C achieved the best S01 gap but did not find an L01 incumbent and therefore is not the best admissible configuration.

No seed 1 run, budget extension, or automatic rerun was performed. Candidate-v2 remains unfrozen.

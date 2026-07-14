# Branch Cleanup Audit

Audit date: 2026-07-14  
Remote: `origin` (`zhangyy0101/Benders`)

The initial working tree was clean after `git fetch origin --prune --tags`. All actual `origin/*` references were enumerated. The public GitHub pull-request page reported **0 open pull requests**; `gh` was unavailable locally and the anonymous REST API was rate-limited, so the public page was used as the read-only fallback.

## Remote branch inventory

| Branch | Head SHA | Merge base with `origin/main` | Unique commits | Purpose | Containment | Recommendation |
|---|---|---|---:|---|---|---|
| `main` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 0 | Original stable upload | Ancestor of every audited branch | Keep; later update only under stage 04 |
| `paper-exp-v1-development` | `b5e288bbbba773c65cd5e2f2879f227880357b35` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 28 | Paper-exp-v1 and Pilot1/Pilot2 framework | Contained by Pilot2.1 and candidate-v2 branches | Delete only after the complete cleanup sequence |
| `paper-exp-v1-pilot21-development` | `a4b8b2a65d5be62dc8118697f2732e16e81678dd` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 33 | Pilot2.1, P0-P4, candidate-v1 freeze | Contained by candidate-v2 branch | Delete only after the complete cleanup sequence |
| `algorithm-candidate-v2-development` | `7afe6664ae271e9d2de2508c688b61bc064c0dc1` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 36 | P5 followed by P6A/P6B LB strengthening screen | Current tip only on this branch; archived by the P6B tag | Delete only after the replacement UB branch exists |
| `route-b-true-benders` | `2120e50e81b2b20a6fd05c31fd560a23c7beaa86` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 14 | Early Route B true-Benders development | Fully contained by later paper/candidate branches; lightweight tag `pre-paper-exp-v1` also exists | Delete only after the complete cleanup sequence |
| `route-a-mip-alns` | `897913dd2bc81e41b122e47efc5c880e69fd98c4` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` | 9 | Independent Route A MIP-ALNS development | Not contained by any other remote branch | Unresolved: retain until a dedicated annotated archive tag is explicitly established |

No branch was deleted in stage 01.

## P5 boundary

The unique P5 completion commit is:

```text
2f34af5b9addd08d5070500074624bac616f76e8
clean candidate v1 entrypoints before v2 development
```

It contains:

- `scripts/run_candidate_experiments.py`;
- `scripts/run_candidate_v1_smoke.py`;
- configuration-driven `main.py`;
- `tests/test_candidate_v1_immutability.py`;
- `docs/P5_CLEANUP_REPORT.md` and the status consistency update.

It precedes P6A commit `1615ddd00d3ee36aef7cb7dc91ae50b3f7d36980` and P6B commit `7afe6664ae271e9d2de2508c688b61bc064c0dc1`. Its tree contains no P6A report, candidate-v2 fast-screen runner/results, or registered V2A/V2B/V2C configuration. A `pod_size` string occurs only in a label-resolution compatibility unit test, not in an implementation or registered configuration.

## Archive tag mapping

| Annotated tag | Peeled commit |
|---|---|
| `archive/initial-main` | `12bf4a9e3b65dd39dc828214b698cebee9988b63` |
| `archive/paper-exp-v1-development` | `b5e288bbbba773c65cd5e2f2879f227880357b35` |
| `archive/pilot21-candidate-v1` | `a4b8b2a65d5be62dc8118697f2732e16e81678dd` |
| `archive/candidate-v1-p5-cleanup` | `2f34af5b9addd08d5070500074624bac616f76e8` |
| `archive/candidate-v2-lb-screened-out` | `7afe6664ae271e9d2de2508c688b61bc064c0dc1` |

Existing tags were not moved. Stage 01 does not update `main` or delete remote branches.

# Evidence hierarchy

Evidence is interpreted in this order:

```text
P1 correctness evidence
< P2 internal screening
< P3 adaptive confirmation
< P4 candidate freeze decision
```

- P1 establishes correctness and finite-time consistency.
- P2 and P3 are development evidence used to compare provisional configurations.
- P4 is the authoritative freeze decision for `algorithm-candidate-v1` and overrides provisional component recommendations.

In particular, P3's temporary recommendation to retain valid inequalities is not the frozen conclusion. P4 froze candidate-v1 with exact BBC, the global recourse oracle, feasibility/optimality cuts, and the size-level aggregate recourse lower bound only.

Historical P1–P3 files are immutable evidence. They must not be deleted, rewritten, or silently combined with candidate-v2 results.

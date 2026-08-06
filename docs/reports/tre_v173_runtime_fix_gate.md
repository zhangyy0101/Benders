# TRE v1.7.3 global-repair runtime gate

Version 1.7.3 corrects the controller defect exposed by preflight candidate v3.
It does not alter the mathematical model, lexicographic objectives, operation
weights, recovery policy, or common per-cycle online budget.
The implementation is frozen in commit
`bdd4f5331c3aea7d33bdcca57e3dd727908acfbb`.

The controller now reserves 25% of the original online limit for unrestricted
safety repair, subject to the existing 0.5--20 second bounds. It also requires
a build window equal to one sixth of the online limit, capped at 10 seconds,
both when repair is enqueued and immediately before unrestricted model
construction. At the frozen 60-second preflight budget these rules give a
15-second reserve and a 10-second admission floor. The complete policy is
written into every experiment's weight-profile metadata.

The full suite passes with 173 tests and 9 subtests. Both candidate-v3 failure
instances were then rerun with one thread, a 1% MIP gap, business weights, and
the unchanged 60-second limit:

| Instance | Old maximum cycle (s) | v1.7.3 maximum cycle (s) | Global repairs | Deadline misses | Final unplaced |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pnc_yangshan_volume_low_low_n4_seed700` | 60.687 | 57.702 | 2 | 0 | 0 |
| `pnc_yangshan_yard_observed_observed_n4_seed700` | 65.594 | 56.242 | 1 | 0 | 0 |

Both one-row manifests have `complete=true` and `all_ok=true`; neither run
skipped a required global repair for insufficient time. These dirty-tree
development runs are directional regression evidence only. They authorize
freezing candidate v4 and rerunning preflight from zero, not formal execution.

Artifact hashes:

- volume-low CSV:
  `7641bdf5585ebd76ef78160f47bddb282ceed2bdac2ebb5bcd5427d989810e9`;
- volume-low manifest:
  `23be11744165946a0dcd66c0a634359e9467626ce4423f64e5334af1077b4a33`;
- yard-observed CSV:
  `093b3dac463240678a2472ddcdc8208344d00b28f5e9abb4abb72a6457d97875`;
- yard-observed manifest:
  `1c72fad9b5eb4dd8ca14835584b92c26c62b72dcf4894f231ac4d274ac694acc`.

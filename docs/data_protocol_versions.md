# Data protocol version registry

This registry separates historical experiment evidence from the formal
PNC--Yangshan redesign. Results from different protocols must not be pooled or
written to the same output directory.

## V1: Sinsundae capacity-calibrated semi-synthetic data

- Status: historical development evidence
- Source terminal: Sinsundae Container Terminal
- Public source periods: March, July, and November 2025
- Demand protocol: `portmis-demand-v1`
- Code baseline: `d4c61438ff6c4d1749cfae5eb94bc1ff253c9617`
- Git tag: `pre-pnc-yangshan-v1`
- Existing incomplete formal public matrix: 15 of 210 expected rows

The incomplete V1 public matrix must not be resumed or reported as a completed
formal experiment. Existing V1 files are retained locally and must not be
overwritten by V2 runs. Unchanged, hash-verified fully synthetic scale and
pressure instances may be reviewed separately for reuse.

## V2: PNC--Yangshan data-driven semi-synthetic data

- Status: data-family allocation and exact formal instance specification
  frozen; seed-1000--1009 bundle generation and hashes pending
- Development branch: `research/pnc-yangshan-formal-v2`
- Source terminal: PNC / Busan New Port Pier 2
- Candidate primary source period: May 2026
- Verified primary PNC operator panel: May 2026 (111 scheduled calls; 104
  positive-export calls; five berths)
- PNC temporal robustness panels: March, April, and June 2026
- Candidate scale windows:
  - 2026-05-08 through 2026-05-10
  - 2026-05-14 through 2026-05-20
  - 2026-05-21 through 2026-05-31
- Vessel skeleton: observed PNC operator berth-schedule calls
- Model demand boundary: export containers only
- Export box total: PNC operator-published loading quantity
- PORT-MIS role: supplementary vessel attributes and independent validation
- Box attributes: Yangshan-calibrated `(POD, 20/40 ft, height)` groups
- Yard: model-compatible virtual yard calibrated from Yangshan snapshots
- Yangshan calibration snapshots: May 8 and May 19, 2026
- Held-out Yangshan validation snapshot: May 25, 2026
- Yangshan voyage predictions: excluded from calibration and formal experiments
- Height mapping: `HQ -> HIGH`, `PQ/MQ -> STD`; model classes remain unchanged
- PNC panel status: built and source-audited
- Per-call box-volume anchor: PNC operator-published loading quantity
- PNC source panel: 440 calls, including 421 positive-export calls
- PORT-MIS validation: 428/428 PORT-MIS calls matched one-to-one; 428/440 PNC
  calls independently validated
- Volume sensitivity: 0.8/1.0/1.2 times observed PNC export loading quantity
- PNC annual capacity: reasonableness check only, never the call-volume baseline
- Export attribute disaggregation: built and source-audited
- Attribute generator: size-matched Yangshan observed-voyage profile bootstrap
- Model-ready baseline: 421 PNC export calls, 484,262 boxes, 6,803 joint groups
- Per-call POD support: 1--12, median 6
- Yangshan yard scope: only functions containing `OF`
- Export yard anchor: 74 active areas, 2,789--2,819 bays, five tiers,
  75,841--76,501 slot rows
- Virtual-yard generation status: built and source-audited
- Formal-instance assembly status: the declared eight-scenario preflight
  matrix is frozen and generated for seeds 700--702; formal held-out bundles
  are not yet generated
- Integer certificate status: all 11 accepted preflight bundles certified
  feasible
- Pilot yard scaling: six complete `capacity_relief_080` OF-calibrated areas,
  228 bays, with free slots at least 3.0 times incoming booking boxes; the
  initially tested 1.25 factor was rejected as structurally overloaded
- Full-window scalability check: the complete ten-call May 8--10 candidate
  returned `unknown` within the 60-second integer-certificate limit and is
  excluded from the frozen preflight index
- Semi-synthetic algorithm preflight: a repeated-scan defect in bottleneck
  preprocessing was removed without changing the selector formulation;
  selector time fell from 113.73 to 1.78 seconds and representative unplaced
  demand fell from 1,441 boxes (33.15%) to 18 boxes (0.414%)
- Candidate implementation: `lead-aware-aggregate-lp-screened-repair-v1.4.1`
- Physical-capacity execution recovery: protocol
  `rolling-v4.4-physical-capacity-recovery`, candidate version 1.4.2, and result
  schema v10. The final deterministic recourse now searches every physically
  compatible OF bay rather than only bays carrying a same-ship/same-group
  reservation. Any future reservation displaced by this use is reduced, so
  capacity is not counted twice. The May seed-700 representative case placed
  all 4,347 realized export boxes with zero unplaced; 755 boxes required this
  reservation-domain recovery and 333 units of future reservation were
  displaced.
- Sparse derived-inventory formulation: candidate version 1.4.3 and
  preprocessing implementation `sparse-indexed-v5`. Inventory variables used
  only for reporting were removed from the MIP and are now derived exactly
  from arrival decisions. Repeated per-period cumulative-flow bounds were
  replaced by the equivalent bay-level reservation-flow equality. On the same
  May seed-700 case, maximum variables fell from 1,438,567 to 681,463 and
  maximum constraints from 1,847,351 to 344,253. Total online decision time
  fell from 219.79 to 143.92 seconds while all 4,347 realized boxes remained
  placed and every validation check passed.
- Deterministic repair-budget routing: candidate version 1.4.4. Repeated
  solves of the identical initial snapshot exposed final predicted shortages
  of 551, 446, and 2,734 under the old mechanical half-budget split. The
  global stage did not return a solution in any repetition. The bottleneck
  repair now receives the remaining recovery window and terminates the cycle
  when it has returned a feasible improved incumbent; global recovery remains
  the safety route when bottleneck-domain selection or solution fails.
  Repeated fixed-snapshot paths then remained
  `aggregate_screened_impact_region -> bottleneck_repair`, with no 2,734-box
  failure. Two complete rolling repetitions required only 4 and 6 physical
  recovery placements, respectively, and both had zero final unplaced boxes.
- Resource-isolated global-core stabilization: candidate version 1.4.7.
  Paired-process preflight runs on one workstation were invalidated because
  competing model construction and memory pressure consumed the common wall
  budget. Ordinary aggregate-routed global-core stages now retain the dynamic
  stability budget and use `MIPFocus=1`, `Heuristics=0.20`, and a 2,000-node
  MIP-start repair limit. Explicit post-shortage global recovery may still
  lift the stability budget. A sequential rerun of all eight seed-700 bundles
  completed every cycle with zero final unplaced boxes and three physical
  recovery placements among 35,623 arrivals. Sequential repetitions on seeds
  701 and 702 also passed all 16 bundles. Across the declared 24-run gate,
  all 106,499 arrivals were placed, 31 used physical recovery, no cycle
  exceeded 46.47 seconds, and there were no no-incumbent or validation
  failures.
- Formal-result authorization: true for frozen candidate version 1.4.7.
  This authorizes the algorithm version, not immediate execution of the formal
  dataset. Formal seeds must remain unopened until the exact instance
  specification, baseline interface gate, clean-code freeze, and formal run
  manifest are fixed. No subsequent algorithm or parameter tuning is
  permitted.
- Formal data-family allocation: frozen in
  `docs/pnc_yangshan_formal_data_allocation.md`. PNC--Yangshan semi-synthetic
  data support the main external-validity, temporal, export-volume, and
  yard-calibration panels. Fully synthetic data support computational scale,
  controlled pressure, forecast-error, ablation, and repair-mechanism panels.
- Formal semi-synthetic instance specification: frozen as eight profiles per
  seed and 80 bundles across seeds 1000--1009. The central May bundle produces
  50 five-method rows; seven robustness profiles produce 140 paired
  candidate/`core_start` rows. Formal bundle hashes remain pending generation.

V2 changes the data protocol only. The mathematical model, supported box
attributes, constraints, candidate algorithm, external baselines, evaluator,
and validation boundary remain frozen unless a later protocol revision
explicitly states otherwise.

## Local data and result isolation

The raw `data_analysis/` directory and generated `local_results/` directory are
local-only and ignored by Git. Raw terminal data must be represented in the
repository by audited schemas, provenance records, and cryptographic file
hashes rather than by committing the source files.

New V2 artifacts must use a separate root:

```text
local_results/protocol_v2_pnc_yangshan/
```

V1 artifacts remain under their existing locations until a non-destructive
archive inventory has been generated. No V1 file may be deleted, moved, or
renamed merely to prepare V2.

## Five-method preflight completion

The algorithm-interface gate is complete for seeds 700--702: 24 immutable
semi-synthetic instances were evaluated by the candidate, `core_start`, and
three external baselines, producing 120 valid rows. All methods achieved zero
final unplaced boxes; no validation or online-deadline failure occurred.
Candidate version 1.4.7 and external-baseline protocol v1.1 are frozen for the
formal manifest. The audited merged-result SHA-256 is
`7ac1ecc7a621cb1136acfdf3bc9dcd308722034fd339ad9016f417259104af01`.

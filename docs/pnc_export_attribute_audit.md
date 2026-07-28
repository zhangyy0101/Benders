# PNC export-attribute disaggregation audit

## Data roles

- PNC supplies the observed vessel-call skeleton and positive export loading
  total for each call.
- Yangshan observations supply joint `(POD, 20/40 ft, STD/HIGH)` composition
  and voyage-level POD heterogeneity.
- PORT-MIS remains supplementary validation and contributes no box attribute.
- Yangshan predictions and PNC discharge quantities are excluded.

The mathematical model and its attribute boundary are unchanged.

## Why voyage profiles are used

After restricting yard observations to export-capable `OF` areas, the pooled
Yangshan calibration contains 354 joint groups over 143 PODs.
Applying that entire distribution independently to every PNC call would assign
about 100 PODs to a typical vessel, which is not consistent with the observed
Yangshan voyages and would unnecessarily enlarge the optimization instances.

After container-level deduplication, the two calibration snapshots contain 121
observed export-voyage profiles. Their distinct POD count ranges from one to
12. The generator therefore bootstraps a complete observed joint voyage
profile rather than sampling POD, size, and height independently.

For every PNC call, the algorithm:

1. finds the 30 Yangshan voyage profiles nearest in log observed box count;
2. selects reproducibly among them while minimizing the remaining aggregate
   deviation from the pooled Yangshan joint distribution;
3. rescales the selected profile to the PNC call total using largest-remainder
   integer allocation;
4. repeats separately for the 0.8, 1.0, and 1.2 volume scenarios.

The fixed seed is `20260728`. The held-out May 25 snapshot is never considered
when selecting or rescaling profiles.

## Audit results

The observed-volume baseline contains:

- 421 positive-export PNC calls;
- 484,262 observed export boxes;
- 484,262 boxes after group disaggregation;
- 864,688 generated TEU;
- 6,803 positive model-ready group rows;
- one to 12 PODs per call, with median six.

All 1,263 call-scenario rows reconcile exactly to their group rows. There are
no nonpositive groups, unsupported sizes, unsupported height classes, unknown
calls, or call-total conservation failures.

For the observed-volume scenario, monthly joint total-variation distance to
the Yangshan calibration distribution is:

| Period | Joint TV | POD TV | Size TV | Height TV |
|---|---:|---:|---:|---:|
| March 2026 | 0.0141 | 0.0124 | 0.0007 | 0.0006 |
| April 2026 | 0.0161 | 0.0139 | 0.0006 | 0.0004 |
| May 2026 | 0.0155 | 0.0143 | 0.0003 | 0.0005 |
| June 2026 | 0.0157 | 0.0140 | 0.0009 | 0.0013 |

The higher distance to the held-out distribution, approximately 0.30 at the
joint level, reflects the previously documented temporal POD shift. It is
reported as validation evidence rather than removed through data leakage.

## Outputs and readiness

`export_calls_model_ready.csv` and `export_groups_model_ready.csv` contain the
1.0 observed-volume baseline. The corresponding `*_scenarios.csv` files
contain all three scale cases. Each manifest records source and output hashes,
the random seed, protocol version, and field origins.

This layer passes its audit and is ready for virtual-yard construction. The V2
dataset is not yet ready for formal algorithm comparison because a
Yangshan-calibrated, model-compatible virtual yard and complete instance
validator still have to be built.

## Reproduction

```powershell
python scripts/build_yangshan_observed_calibration.py
python scripts/build_pnc_observed_call_volumes.py
python scripts/disaggregate_pnc_export_attributes.py
python analysis/plot_pnc_export_attributes.py
```

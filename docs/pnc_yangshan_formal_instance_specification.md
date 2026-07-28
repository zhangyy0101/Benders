# PNC--Yangshan V2 formal instance specification

## Frozen semi-synthetic matrix

The semi-synthetic formal matrix uses eight unique profiles for each of the
held-out seeds 1000--1009. It therefore contains 80 immutable instance
bundles. Formal seeds are declared here but remain unopened until the baseline
interface and clean-code gates pass.

| Profile | PNC window | Calls | Volume | Yard | Methods |
|---|---|---:|---:|---|---|
| `volume_baseline` | 2026-05-14--20 | 4 | observed, 4,314 boxes | `capacity_relief_080` | five-method main comparison |
| `temporal_mar` | 2026-03-14--20 | 4 | observed, 4,716 boxes | `capacity_relief_080` | candidate + `core_start` |
| `temporal_apr` | 2026-04-14--20 | 4 | observed, 4,310 boxes | `capacity_relief_080` | candidate + `core_start` |
| `temporal_jun` | 2026-06-14--20 | 4 | observed, 4,747 boxes | `capacity_relief_080` | candidate + `core_start` |
| `volume_low` | 2026-05-14--20 | 4 | 0.8, 3,451 boxes | `capacity_relief_080` | candidate + `core_start` |
| `volume_high` | 2026-05-14--20 | 4 | 1.2, 5,177 boxes | `capacity_relief_080` | candidate + `core_start` |
| `yard_observed` | 2026-05-14--20 | 4 | observed, 4,314 boxes | `observed_full` | candidate + `core_start` |
| `yard_high_pressure` | 2026-05-14--20 | 4 | observed, 4,314 boxes | `high_pressure` | candidate + `core_start` |

The May `volume_baseline` bundle is reused as:

- the central five-method external-validity case;
- the May member of the March--June temporal panel;
- the 1.0 member of the export-volume panel;
- the `capacity_relief_080` member of the yard panel.

It is one immutable bundle, not four duplicated observations.

## Common construction

- Four chronologically first positive-export calls are selected from each
  frozen seven-day window. Exact PNC call IDs are stored in the machine
  specification.
- Forty complete OF-calibrated areas are selected using the frozen
  observed-free-slot ranking. Areas are never split.
- Minimum free capacity is three times the incoming booking boxes at assembly.
- Forecast setting is 10% multiplicative error. Forecast-error sensitivity is
  handled by the fully synthetic family, not by this panel.
- Each rolling cycle has a 60-second strict online-decision budget.
- Box groups remain `(POD, 20/40, STD/HIGH)`.
- PNC published loading quantities are the only call-total anchor.
- Yangshan supplies the complete-voyage-profile attribute bootstrap and
  OF-yard calibration.
- PORT-MIS supplies supplementary vessel fields and independent validation;
  it does not generate demand.

The reference capacity-relief yard has 40 areas, 1,519 bays, 41,128 slots,
and 21,033 initially locked boxes. The observed yard has 1,526 bays, 41,335
slots, and 19,535 initially locked boxes. The high-pressure yard has 1,518
bays, 41,121 slots, and 22,798 initially locked boxes. Exact generated values
must still be repeated in every formal bundle and manifest.

## Expected result matrix

- Central May bundle: 10 seeds x 5 methods = 50 rows.
- Seven noncentral robustness bundles: 7 profiles x 10 seeds x 2 methods =
  140 rows.
- Total semi-synthetic formal results: 190 rows.

The five central methods are `core_start`, `full_bottleneck`, `kp_dos`,
`kp_sg`, and `dra_rpm`. Robustness panels use `core_start` and
`full_bottleneck`. All methods within a bundle share its realization and time
budget.

## Fully synthetic specification

The previously frozen fully synthetic settings remain unchanged:

- computational scale: small, medium, large, and xlarge;
- capacity targets: `ordinary=0.70` and `high_pressure=0.85`, tolerance 0.03;
- scale-panel initial utilization: 0.55;
- utilization isolation: medium size at 0.25, 0.55, and 0.65;
- baseline synthetic forecast setting: 10% mixed error;
- formal seeds: 1000--1009;
- per-cycle budgets: 20 seconds for small and medium, 60 seconds for large,
  and 120 seconds for xlarge;
- every accepted performance instance requires an integer zero-shortage
  certificate;
- controlled overloaded or repair-pressure instances remain separately
  labelled mechanism evidence.

The existing synthetic generator and constants define the exact vessel, yard,
and horizon presets. No PNC calls or Yangshan yard records are inserted into
the fully synthetic scale, forecast-error, ablation, or pressure panels.

## Freeze boundary

The source windows, selected call IDs, call count, yard-area count, volume
factors, yard profiles, forecast setting, time budget, seeds, method sets, and
expected counts are now frozen. Formal bundle hashes are intentionally not
present yet because the formal bundles have not been generated.

The authoritative machine-readable specification is
`docs/specs/pnc_yangshan_v2_formal_instance_spec.json`. A later change to a
frozen field requires a new specification version and cannot be justified by
formal algorithm outcomes.

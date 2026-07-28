# PNC observed call-volume audit

## Source and interpretation

Call-level container work is taken from the PNC operator's public berth
schedule:

```text
https://svc.pncport.com/info/CMS/Ship/Info.pnc?mCode=MN014
```

The schedule publishes vessel identity, carrier voyage, berth and departure
times, berth, loading quantity, and discharge quantity. It is the primary
source for the vessel-call panel and box total. Because the model covers
export containers only, its formal volume field is the published loading
quantity. Discharge quantity is audit-only.

## PNC primary-panel rule

The PNC query returns several preceding-month boundary rows. A call belongs to
a monthly panel only when its PNC berth timestamp falls within that month.
This produces:

| Period | PNC source calls | Positive export calls | Zero export calls | Export boxes |
|---|---:|---:|---:|---:|
| March 2026 | 118 | 115 | 3 | 136,755 |
| April 2026 | 104 | 97 | 7 | 106,927 |
| May 2026 | 111 | 104 | 7 | 120,202 |
| June 2026 | 107 | 105 | 2 | 120,378 |
| **Total** | **440** | **421** | **19** | **484,262** |

The 421 positive-loading calls form the model's export-demand panel. The 19
zero-loading calls remain in the complete source table but are excluded from
demand generation. No volume is imputed.

## Independent PORT-MIS validation

PORT-MIS calls and PNC rows are joined by exact normalized vessel name. A
one-to-one assignment minimizes the combined absolute entry/berth and
departure-time discrepancy, with a 96-hour rejection threshold. All 428
PORT-MIS calls match one-to-one to the PNC panel. This validates 428/440 PNC
source calls and 419/421 positive-export calls. The median combined score is
0.13 hours and the 95th percentile departure-time error is 0.23 hours.

The 12 PNC rows without PORT-MIS counterparts are not discarded: PORT-MIS is
an external check and supplementary vessel-attribute source, not a sample
selection rule.

## Scale sensitivity and capacity check

The observed loading quantity is the 1.0 baseline. The generated protocol also
records 0.8 and 1.2 integer-rounded scale cases for demand sensitivity.

PNC states annual handling capacity of five million TEU or more:

```text
https://www.pncport.com/eng/Info/details.do?id=MD032
```

Applying the Yangshan-observed mean of 1.767 TEU per box to both loading and
discharge quantities gives an approximate annualized total-work check of 5.30
million TEU, or 1.060 times the nominal five-million-TEU figure. This
supports gross consistency only: the Yangshan size mix is not an observed PNC
size mix, and the operator describes capacity as at least five million TEU.
Capacity is therefore never used to determine a call's box count.

## Data boundary and readiness

Yangshan observations remain appropriate for the joint POD/20-or-40/STD-or-HIGH
attribute distribution and for virtual-yard calibration. They are incomplete
per voyage and are not used as PNC call totals. Yangshan prediction files stay
excluded.

This export-volume layer passes its audit and is ready for attribute
disaggregation.
The full V2 instances are not ready for formal experiments until every
observed call total is integer-disaggregated into the model-compatible joint
groups and the resulting instances pass the existing yard and model
validators.

## Reproduction

```powershell
python scripts/fetch_pnc_work_moves.py
python scripts/build_pnc_observed_call_volumes.py
python analysis/plot_pnc_observed_volumes.py
```

Local tables, manifests, raw archived pages, PDF figures, 400-dpi PNG figures,
plot data, and captions are stored below
`local_results/protocol_v2_pnc_yangshan/`.

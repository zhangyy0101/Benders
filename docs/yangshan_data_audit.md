# Yangshan data audit

## Scope and evidence boundary

This audit covers every file below `data_analysis/`, while using only the
canonical raw snapshots in:

- `pro_test_data_0508/原始数据`
- `pro_test_data_0519/原始数据`
- `pro_test_data_0525/原始数据`

The three evidence layers are deliberately not merged as if they were
equivalent:

1. `bay_slots_detail.parquet` records containers physically present in the
   yard at a snapshot.
2. `container_info_<voyage>.parquet` records declared export containers that
   have not yet entered the yard.
3. `voyage_predict.json` and the matching Excel workbooks predict all
   containers for a voyage, but are not observed ground truth.

Import-discharge records are inventoried separately. Algorithm inputs and
outputs (`input_data.json`, result/plan Parquet files, and the dated
`data*` directories) are excluded from empirical calibration.

## File and snapshot audit

- 185 files were inventoried and hashed.
- 111 canonical, non-algorithm files were selected as source evidence.
- 40 algorithm or derived-artifact files were excluded.
- 25 duplicate-content groups were detected. In particular, the 0519 root
  directory repeats files from its `原始数据` directory; these copies are not
  counted twice.
- The snapshots are May 8, May 19, and May 25, 2026. They are separated by
  11 and 6 days, so they are repeated cross-sections rather than a continuous
  daily panel.

| Snapshot | Yard slot rows | Occupied slot rows | Unique yard containers | Export-voyage yard containers | Declared-not-in-yard records | Predicted voyages |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-08 | 166,520 | 88,218 | 49,922 | 27,323 | 1,741 | 2 |
| 2026-05-19 | 167,000 | 83,101 | 46,383 | 29,215 | 1,990 | 13 |
| 2026-05-25 | 166,448 | 92,736 | 52,103 | 36,619 | 580 | 15 |

A 40/45-foot container can occupy two rows in `bay_slots_detail`. Therefore,
occupied slot rows are valid for yard utilization, but all container-volume
and attribute calculations deduplicate on `IYC_CNTRID`.

Those totals describe the whole yard and must not be used as export-yard
capacity. The yard-function workbook marks 70 areas as `OF` and 14 mixed-use
areas with an `OF` token. Of these 84 export-capable labels, 74 occur in the
slot snapshots. The resulting export-yard scope contains 75,841--76,501 slot
rows, 2,789--2,819 bays, five tiers, and slot-row utilization of
48.01%--57.25%. Areas whose function list does not contain `OF` are excluded
from export-yard calibration and from yard-observed export-box evidence.

One yard-entry timestamp from 2012 persists in every snapshot, so entry
timestamps require outlier filtering before dwell-time analysis.

## Relationships among the three evidence layers

Across snapshots there are:

- 129,402 unique containers observed anywhere in the yard;
- 87,622 unique yard containers carrying an export voyage ID;
- 4,311 unique declared-not-in-yard export containers;
- 290 containers observed in both document and yard states across snapshots;
- 285 of those 290 appearing in a document snapshot before a later yard
  snapshot.

Within the same snapshot, the yard/document container-ID overlap is zero on
May 8 and May 19, and five on May 25. These five records are data-state
exceptions and must be unioned by container ID rather than added twice.

There are 317 `snapshot × voyage` rows with at least one evidence source:

- 41 have both yard and document evidence;
- 29 have yard, document, and prediction evidence;
- 30 predicted voyages have a nonzero observed lower bound.

For a voyage, the union of yard-observed and declared-not-in-yard containers is
only an **observed lower bound**. It is not the actual voyage total because
undeclared containers may still exist.

All 30 prediction workbooks exactly reproduce their corresponding JSON totals.
This confirms internal file consistency, not prediction accuracy. Among the 30
comparable voyage-snapshot rows:

- the median `observed lower bound / predicted 20/40 total` is 1.093;
- the range is 0.320--31.571;
- 16 predictions are below the already-observed lower bound;
- voyage `454804` is the strongest anomaly: predicted 42 versus an observed
  lower bound of 1,326.

Consequently, predicted totals are excluded from formal-data calibration and
formal experiments. Forecast uncertainty is represented by the model's
existing parameterized bias and random-error mechanism.

## Model-compatible empirical distributions

For pooled attribute calibration, the audit takes the latest state of each
container across snapshots, gives a yard observation priority over a document
record within the same snapshot, and then retains only:

- size 20 or 40 feet;
- a known discharge port;
- a supported height mapping: `HQ → HIGH`, `PQ/MQ → STD`.

This produces 57,957 unique observed export containers across the three
OF-filtered snapshots. It does not change the model's supported attributes.

Export direction is identified by nonmissing `IYC_EVOY_ID`, not merely by
presence in a yard snapshot. Boxes carrying only `IYC_IVOY_ID` are excluded;
boxes carrying both IDs are retained because an outbound voyage is assigned.
The declared-box files match their embedded export voyage IDs. `CNSHA` POD
records are excluded as export-direction anomalies.

| Size | Height | Unique containers | Share of pooled sample |
|---:|---|---:|---:|
| 20 | STD | 12,198 | 21.05% |
| 20 | HIGH | 285 | 0.49% |
| 40 | STD | 2,471 | 4.26% |
| 40 | HIGH | 43,003 | 74.20% |

The observed 40-foot share is 78.46%; among observed 40-foot boxes, 94.57% are
high-cube. The prediction layer contains 45,948 predicted 20/40-foot boxes
across 30 voyages and 97 discharge ports, with a 78.55% 40-foot share. The
similar aggregate size shares do not remove the large voyage-level forecast
errors.

The leading observed discharge ports are MYTPP (9.22%), NLRTM (5.71%), DEWVN
(4.21%), USLAX (3.80%), USLSA (3.49%), and GBLGP (3.39%). Formal synthesis
should preserve the full or truncated empirical POD distribution explicitly,
rather than interpreting the most frequent ports as a PNC route list.

## Permitted use in the reconstructed dataset

The audited Yangshan data can support:

- POD, 20/40-foot size, and STD/HIGH height composition;
- cross-attribute joint distributions;
- realistic yard capacity, topology, and utilization ranges;
- declared-share diagnostics;
- snapshot-based robustness or validation splits.

It cannot, by itself, support:

- a continuous Yangshan operational time series;
- exact true totals for the sampled voyages;
- treating document records as all voyage containers;
- treating predictions as observations;
- adding yard, document, and predicted volumes together;
- importing Yangshan vessel identities into the PNC vessel-call panel.

The formal PNC--Yangshan dataset should therefore use PNC calls as the vessel
and timing skeleton, Yangshan's deduplicated observed export boxes as the
attribute calibration sample, the Yangshan yard snapshots as yard calibration,
and prediction discrepancies only as a forecast-uncertainty layer.

## Reproduction

Run:

```powershell
python scripts/audit_yangshan_data.py
```

Aggregate audit outputs are written to
`local_results/yangshan_data_audit/`:

- `audit_summary.json`
- `file_inventory.csv`
- `snapshot_summary.csv`
- `voyage_coverage.csv`
- `attribute_distributions.csv`
- `prediction_pod_distributions.csv`
- `model_compatible_observed_groups.csv`
- `cross_snapshot_transitions.csv`

The transition table contains hashed container identifiers only; the other
outputs are aggregate-only.

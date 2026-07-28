# Yangshan-calibrated virtual-yard audit

## Export-yard boundary

The virtual yard is calibrated only from Yangshan areas whose function list in
`箱区功能.xlsx` contains the token `OF`. This includes 70 pure `OF` areas and
14 mixed-function areas. Ten listed labels have no rows in the three slot
snapshots, leaving 74 active export-capable areas.

| Snapshot | Active OF areas | Slot rows | Bays | Tiers | Occupied rows | Utilization |
|---|---:|---:|---:|---:|---:|---:|
| May 8 | 74 | 76,181 | 2,819 | 5 | 36,574 | 48.01% |
| May 19 | 74 | 76,501 | 2,819 | 5 | 37,886 | 49.52% |
| May 25 | 74 | 75,841 | 2,789 | 5 | 43,416 | 57.25% |

Areas marked only `IF`, `IZ`, `OZ`, or `T` do not contribute capacity,
occupancy, or yard-observed export-box evidence. Declared export boxes not yet
in the yard remain valid attribute evidence because they have no yard location
to filter.

Container direction is filtered independently from yard function. A retained
record must have a nonmissing `IYC_EVOY_ID`; records carrying only
`IYC_IVOY_ID` are imports and are excluded. Records carrying both IDs remain
valid because they have an assigned outbound export voyage. The declared-box
files were verified against their embedded `IYC_EVOY_ID`. Twelve OF-area
export-voyage records with `CNSHA` as POD are treated as direction/port
anomalies and excluded.

## Demand linkage

Yard scale is checked against the 421 PNC positive-export calls. The main
diagnostic is a dynamic net-inventory trajectory: boxes enter through the
existing 12-period receiving curve, leave at PNC departure, and initial
owners release under the model's whole-owner release rule. A separate
all-boxes-overlap calculation is retained only as an upper-bound sizing aid.

The templates are:

| Profile | Areas | Bays | Capacity | Initial utilization | Maximum dynamic load |
|---|---:|---:|---:|---:|---:|
| Observed full OF scale | 74 | 2,819 | 76,341 | 48.77% | 0.748 |
| Capacity relief | 100 | 3,795 | 102,772 | 53.50% | 0.731 |
| High initial utilization | 81 | 3,071 | 83,165 | 57.25% | 0.812 |

The observed-full template is the reality-anchored baseline. The other two are
controlled computational sensitivities. Capacity relief deliberately provides
more virtual capacity than the observed OF footprint; the high-utilization
case uses the held-out occupancy anchor. The earlier 0.80 and 0.90 quantities
are conservative upper-bound design inputs, not claims about typical dynamic
occupancy. Neither sensitivity is claimed to be a physical PNC layout.

## Preserved model constraints

Every bay has a positive integer capacity and is locked to either 20- or
40-foot boxes. Initial inventory is integer, never exceeds 85% of a bay, and
has one STD/HIGH lock for each occupied bay-owner pair. Old inventory receives
a positive six-hour release period. The five-tier value is a physical
calibration label; the optimization model continues to operate on its existing
aggregate bay-capacity representation.

The initial HIGH probability is 0.750, taken from the OF-filtered Yangshan
joint attribute distribution. Old-container release rates are semi-synthetic,
not observed Yangshan or PNC values, and are recorded explicitly.

## Audit conclusion

All three templates pass integer capacity, size coverage, initial utilization,
height lock, release, and dynamic aggregate capacity checks. They are
ready for rolling-instance assembly. Formal algorithm comparison must wait
until the selected call windows are assembled with these templates and receive
zero-shortage integer packing certificates.

## Reproduction

```powershell
python scripts/build_yangshan_observed_calibration.py
python scripts/disaggregate_pnc_export_attributes.py
python scripts/build_yangshan_calibrated_virtual_yard.py
python analysis/plot_yangshan_virtual_yard.py
```

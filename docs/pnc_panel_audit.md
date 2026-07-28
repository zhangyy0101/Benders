# PNC vessel-call panel audit

## Source and terminal mapping

The vessel-call data are associated with the Korean Ministry of Oceans and
Fisheries vessel-operation dataset:

```text
https://www.data.go.kr/data/15006353/openapi.do
```

The catalogue describes a real-time REST/XML service containing port,
arrival/departure time, vessel identity, gross tonnage, previous port, and next
port information. The current development account has no service key.
Therefore, the archived bytes were obtained through the official provider's
guest PORT-MIS query interface bound to the same provider view. Each monthly
snapshot archives the data.go.kr catalogue/page, the PORT-MIS UI definition,
the query parameters, raw responses, and SHA-256 hashes. This acquisition
detail must be disclosed rather than described as a direct service-key API
call.

The PNC mapping is independently verified by the Busan Port Authority:

```text
https://www.busanpa.com/index.bpa?menuCd=DOM_000000103001002005
```

The strict PORT-MIS mapping is:

| Facility code | Subcode | Standard berth |
|---|---|---|
| MSN | 04 | B1 |
| MSN | 05 | B2 |
| MSN | 06 | B3 |
| MSN | 07 | B4 |
| MSN | 08 | B5 |

These labels correspond to Busan New Port Pier 2 berths 1--5. PNC's official
site reports a 2,000 m quay and annual handling capacity above five million
TEU:

```text
https://www.pncport.com/eng/Info/details.do?id=MD025
```

The facility mapping selects observed calls. The capacity figure is used only
as an aggregate reasonableness check; it is not a call-volume anchor.

## Candidate-period comparison

Four consecutive 2026 monthly panels were downloaded and audited.

| Period | Calls | Unique vessels | Active arrival days | Berths | Median stay (h) | Complete daily cycles |
|---|---:|---:|---:|---:|---:|---:|
| March | 115 | 104 | 31 | 5 | 29.1 | 28 |
| April | 100 | 94 | 29 | 5 | 27.0 | 27 |
| May | 106 | 98 | 31 | 5 | 32.4 | 28 |
| June | 107 | 99 | 30 | 5 | 30.8 | 27 |

All 428 records match the strict `MSN-04...08` mapping. There are no duplicate
call IDs, missing required identities/timestamps/berths, or departures before
arrival. Every month covers all five PNC berths.

## Validation-panel selection

May 2026 is selected as the primary PORT-MIS validation panel because:

- it aligns with the month of the Yangshan observations;
- it contains 106 calls by 98 vessels;
- arrivals occur on all 31 calendar days;
- it supplies 28 complete rolling daily cycles;
- all five PNC berths are represented;
- every source-quality gate passes.

March, April, and June are retained as temporal-robustness panels. March is not
selected merely because it has the largest call count; alignment and source
quality are more important than maximizing one month's sample size.

The earlier 2025 March/July/November Sinsundae panels are not pooled with this
PNC protocol.

## Permitted data use

The following fields are observed and may be used:

- vessel and call identity;
- entry and departure times;
- PNC berth;
- gross tonnage as a vessel-scale descriptor;
- previous and next vessel ports as route context.

The following interpretations are prohibited:

- loaded cargo tonnage is not container count;
- next vessel port is not a per-container POD;
- the call panel does not contain box size or height;
- PORT-MIS does not provide the Yangshan box attributes or yard state.

This PORT-MIS panel is not the V2 sample-selection skeleton. It serves as an
independent validation panel and supplies supplementary vessel attributes.
All 428 records match one-to-one to the PNC-primary panel. The PNC operator
schedule contains 440 calls, of which 421 have positive export loading
quantities. The formal dataset is not yet ready for optimization runs because
those export totals must still be disaggregated into model-compatible
POD/size/height groups.

## Reproduction

Build the standardized panel:

```powershell
python scripts/build_pnc_formal_panel.py
```

Generate the figures:

```powershell
python analysis/plot_pnc_panel.py
python scripts/fetch_pnc_work_moves.py
python scripts/build_pnc_observed_call_volumes.py
python analysis/plot_pnc_observed_volumes.py
```

Local outputs are isolated under:

```text
local_results/protocol_v2_pnc_yangshan/pnc_formal_panel/
local_results/protocol_v2_pnc_yangshan/figures/pnc_panel/
local_results/protocol_v2_pnc_yangshan/pnc_observed_call_volumes/
local_results/protocol_v2_pnc_yangshan/figures/pnc_observed_call_volumes/
```

The figure directory contains vector PDF, 400 dpi PNG, underlying plot data,
and suggested English captions.

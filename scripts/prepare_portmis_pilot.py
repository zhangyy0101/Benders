"""Prepare and audit a bounded PORT-MIS public-data source snapshot.

This script intentionally does not build rolling optimization instances.  It
queries the guest-accessible PORT-MIS table linked by the provider's official
``fileData`` catalogue record, keeps the source response immutable, and
produces a standardized snapshot plus an audit report.

By default the output remains a development pilot.  ``--publication-ready``
also archives and validates the official catalogue records, the official
provider-page link, and the PORT-MIS UI definition that binds the table to its
transport endpoint.  This is an official-provider portal export contract, not
a claim that the transport endpoint is the documented service-key OpenAPI.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import html
import json
import math
import re
import statistics
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


OFFICIAL_DATA_PAGE = "https://www.data.go.kr/data/15006353/openapi.do"
OFFICIAL_FILE_PAGE = "https://www.data.go.kr/data/15083024/fileData.do"
OFFICIAL_OPENAPI_CATALOG_URL = (
    "https://www.data.go.kr/catalog/15006353/openapi.json"
)
OFFICIAL_FILE_CATALOG_URL = (
    "https://www.data.go.kr/catalog/15083024/fileData.json"
)
BPA_SINSUNDAE_PAGE = (
    "https://www.busanpa.com/index.bpa?menuCd=DOM_000000103001003005"
)
PORTMIS_MAIN_URL = (
    "https://new.portmis.go.kr/portmis/websquare/websquare.jsp"
    "?w2xPath=/portmis/w2/main/index.xml"
    "&page=/portmis/w2/sp/vssl/vsch/UI-PM-SP-104-02.xml"
    "&menuId=1319&menuCd=M0182"
    "&menuNm=%EC%84%A0%EB%B0%95%EC%9E%85%EC%B6%9C%ED%95%AD%ED%98%84%ED%99%A9"
)
PORTMIS_UI_DEFINITION_URL = (
    "https://new.portmis.go.kr/portmis"
    "/w2/sp/vssl/vsch/UI-PM-SP-104-02.xml"
)
PORTMIS_QUERY_URL = (
    "https://new.portmis.go.kr/portmis"
    "/sp/vssl/vsch/selectSpVsslAllPagingList.do"
)
PORTMIS_QUERY_PATH = "/sp/vssl/vsch/selectSpVsslAllPagingList.do"
PORTMIS_SOURCE_SCHEMA = "portmis-fixed-source-snapshot-v2"
PORTMIS_ACQUISITION_MODE = "official_provider_portal_export"
NO_RESTRICTION_LICENSE_KO = "이용허락범위 제한 없음"
PUBLICATION_EVIDENCE_URLS = {
    "official_openapi_catalog.json": OFFICIAL_OPENAPI_CATALOG_URL,
    "official_file_catalog.json": OFFICIAL_FILE_CATALOG_URL,
    "official_openapi_page.html": OFFICIAL_DATA_PAGE,
    "official_file_page.html": OFFICIAL_FILE_PAGE,
    "official_portal_view.xml": PORTMIS_UI_DEFINITION_URL,
}
CONTAINER_SHIP_CODE = "41"
FINAL_DECLARATION = "최종"
TIMESTAMP_FORMAT = "%Y%m%d%H%M"
DEFAULT_PRIMARY_CLUSTER = "SINSUNDAE"
VERIFIED_TERMINALS = {
    "SINSUNDAE": {
        "terminal_name": "Sinsundae Container Terminal",
        "operator": "Busan Port Terminal Co., Ltd. (BPT)",
        "official_source": BPA_SINSUNDAE_PAGE,
        "official_capacity_teu_per_year": 2_236_000,
        "official_simultaneous_berths": 5,
        "mapping_basis": "facility names 신선대부두 1선석 through 5선석",
    }
}

STANDARD_FIELDS = (
    "call_id",
    "port_code",
    "port_name",
    "vessel_id",
    "callsign",
    "vessel_name",
    "entry_year",
    "entry_sequence",
    "entry_time",
    "departure_time",
    "vessel_kind_code",
    "vessel_kind_name",
    "gross_tonnage",
    "international_gross_tonnage",
    "facility_code",
    "facility_subcode",
    "facility_name",
    "facility_cluster",
    "is_terminal_berth",
    "exclusion_reason",
    "facility_assignment_basis",
    "inbound_facility_code",
    "inbound_facility_subcode",
    "inbound_facility_name",
    "inbound_facility_cluster",
    "outbound_facility_code",
    "outbound_facility_subcode",
    "outbound_facility_name",
    "outbound_facility_cluster",
    "previous_port_country",
    "previous_port_code",
    "previous_port_name",
    "next_port_country",
    "next_port_code",
    "next_port_name",
    "cargo_class_code",
    "cargo_class_name",
    "inbound_loaded_cargo_tonnage",
    "outbound_loaded_cargo_tonnage",
    "inbound_declaration_type",
    "outbound_declaration_type",
    "inbound_in_query_window",
    "outbound_in_query_window",
)


@dataclass(frozen=True)
class QueryResult:
    direction: str
    raw_bytes: bytes
    rows: list[dict[str, Any]]
    reported_total: int


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError:
        return None


def _iso_timestamp(value: Any) -> str:
    parsed = _parse_timestamp(value)
    return parsed.isoformat(timespec="minutes") if parsed else ""


def _percentile(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_call_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    vessel_identity = _clean(row.get("vsslInnb")) or _clean(row.get("clsgn"))
    return (
        _clean(row.get("prtAgCd")),
        vessel_identity,
        _clean(row.get("etryptYear")),
        _clean(row.get("etryptCo")),
    )


def _call_id(key: tuple[str, str, str, str]) -> str:
    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()
    return f"CALL_{digest[:16].upper()}"


def facility_cluster(name: Any) -> tuple[str, bool, str]:
    """Return a label-derived facility cluster without claiming operator identity."""
    text = _clean(name)
    if not text:
        return "UNKNOWN", False, "missing_facility"
    if any(marker in text for marker in ("박지", "묘지", "정박지")):
        return "ANCHORAGE", False, "anchorage_or_mooring_area"
    if text.startswith("신선대부두"):
        return "SINSUNDAE", True, ""
    if text.startswith("신감만부두"):
        return "NEW_GAMMAN", True, ""
    if text.startswith("감만부두"):
        return "GAMMAN", True, ""
    if text.startswith("자성대부두"):
        return "JASEONGDAE", True, ""
    if text.startswith("감천"):
        return "GAMCHEON", True, ""
    if text.startswith("7부두"):
        return "PIER_7", True, ""
    if text.startswith("신항"):
        for number in range(1, 10):
            if f"신항 {number}부두" in text:
                return f"NEW_PORT_PIER_{number}", True, ""
        if "다목적부두" in text:
            return "NEW_PORT_MULTIPURPOSE", True, ""
        return "NEW_PORT_OTHER", True, ""
    return "OTHER_FACILITY", True, ""


def _facility_values(row: dict[str, Any]) -> dict[str, Any]:
    name = _clean(row.get("laidupFcltyNm"))
    cluster, is_berth, exclusion = facility_cluster(name)
    return {
        "code": _clean(row.get("laidupFcltyCd")),
        "subcode": _clean(row.get("laidupFcltySubCd")),
        "name": name,
        "cluster": cluster,
        "is_berth": is_berth,
        "exclusion": exclusion,
    }


def _resolve_service_facility(
    inbound_row: dict[str, Any],
    outbound_row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str]:
    inbound = _facility_values(inbound_row)
    outbound = _facility_values(outbound_row)
    if not inbound_row:
        selected = outbound
        basis = "outbound_only"
        transition = "outbound_only"
    elif not outbound_row:
        selected = inbound
        basis = "inbound_only"
        transition = "inbound_only"
    elif inbound["name"] == outbound["name"]:
        selected = inbound
        basis = "same_inbound_outbound_facility"
        transition = "same_facility"
    elif inbound["is_berth"] and outbound["is_berth"]:
        if inbound["cluster"] == outbound["cluster"]:
            selected = inbound
            basis = "within_cluster_berth_change"
            transition = "within_cluster_berth_change"
        else:
            selected = {
                **inbound,
                "cluster": "MULTI_TERMINAL",
                "is_berth": False,
                "exclusion": "cross_cluster_facility_change",
            }
            basis = "ambiguous_cross_cluster_change"
            transition = "cross_cluster_change"
    elif inbound["is_berth"]:
        selected = inbound
        basis = "inbound_terminal_outbound_nonterminal"
        transition = "terminal_to_nonterminal"
    elif outbound["is_berth"]:
        selected = outbound
        basis = "outbound_terminal_after_nonterminal"
        transition = "nonterminal_to_terminal"
    else:
        selected = inbound
        basis = "nonterminal_only"
        transition = "nonterminal_change"
    return selected, inbound, outbound, basis, transition


def _new_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    opener.addheaders = [
        (
            "User-Agent",
            "Mozilla/5.0 (compatible; PORTMIS-research-snapshot/1.0)",
        ),
        ("Accept-Language", "ko-KR,ko;q=0.9,en;q=0.8"),
    ]
    return opener


def _request(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    timeout: float,
) -> bytes:
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"PORT-MIS request failed with HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"PORT-MIS request failed: {exc.reason}") from exc


def _query_parameters(
    *,
    direction: str,
    port_code: str,
    port_name: str,
    start: date,
    end: date,
    row_limit: int,
) -> dict[str, str]:
    if direction not in {"inbound", "outbound"}:
        raise ValueError("direction must be inbound or outbound")
    return {
        "prtAgCd": port_code,
        "prtAgNm": port_name,
        "clsgn": "",
        "vsslNm": "",
        "ibobprtSe": "1" if direction == "inbound" else "2",
        "reqstSe": "all",
        "currentPageNo": "1",
        "recordCount": str(row_limit),
        "srchBeginEtryndDt": start.strftime("%Y%m%d"),
        "srchEndEtryndDt": end.strftime("%Y%m%d"),
        "loginAt": "N",
    }


def _query_body(parameters: dict[str, str]) -> bytes:
    return json.dumps(
        {"dmaParam": parameters},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must contain a JSON object")
    return value


def _catalog_has_unrestricted_license(catalog: dict[str, Any]) -> bool:
    license_text = str(catalog.get("license", "")).strip()
    return (
        license_text == NO_RESTRICTION_LICENSE_KO
        or "제한 없음" in license_text
        or license_text.lower() in {"no restrictions", "unrestricted"}
    )


def _extract_content_url(page: bytes) -> str:
    text = page.decode("utf-8", errors="strict")
    match = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError(
            "official fileData page does not declare a contentUrl"
        )
    return html.unescape(match.group(1))


def fetch_publication_evidence(
    output_dir: Path,
    *,
    timeout: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Archive evidence that binds the snapshot to the official provider UI."""
    opener = _new_opener()
    payloads: dict[str, bytes] = {}
    for name, url in PUBLICATION_EVIDENCE_URLS.items():
        payloads[name] = _request(
            opener,
            urllib.request.Request(url),
            timeout,
        )

    openapi_catalog = _json_object(
        payloads["official_openapi_catalog.json"],
        "official OpenAPI catalogue",
    )
    file_catalog = _json_object(
        payloads["official_file_catalog.json"],
        "official fileData catalogue",
    )
    if openapi_catalog.get("url") != OFFICIAL_DATA_PAGE:
        raise RuntimeError("OpenAPI catalogue URL does not match the source")
    if file_catalog.get("url") != OFFICIAL_FILE_PAGE:
        raise RuntimeError("fileData catalogue URL does not match the source")
    for label, catalog in (
        ("OpenAPI", openapi_catalog),
        ("fileData", file_catalog),
    ):
        if not _catalog_has_unrestricted_license(catalog):
            raise RuntimeError(
                f"{label} catalogue does not declare unrestricted use"
            )
        creator = catalog.get("creator") or {}
        if creator.get("name") != "해양수산부":
            raise RuntimeError(
                f"{label} catalogue provider is not the Ministry of Oceans "
                "and Fisheries"
            )

    content_url = _extract_content_url(
        payloads["official_file_page.html"]
    )
    if urllib.parse.unquote(content_url) != urllib.parse.unquote(
        PORTMIS_MAIN_URL
    ):
        raise RuntimeError(
            "official fileData contentUrl does not match the PORT-MIS view"
        )
    openapi_page = payloads["official_openapi_page.html"].decode(
        "utf-8", errors="strict"
    )
    if (
        "apis.data.go.kr/1192000/VsslEtrynd5" not in openapi_page
        or '"name":"serviceKey"' not in openapi_page
        or '"required":true' not in openapi_page
    ):
        raise RuntimeError(
            "official OpenAPI page no longer exposes the expected "
            "service-key contract"
        )
    portal_ui = payloads["official_portal_view.xml"].decode(
        "utf-8", errors="strict"
    )
    if PORTMIS_QUERY_PATH not in portal_ui:
        raise RuntimeError(
            "official PORT-MIS UI no longer binds the expected query path"
        )

    declarations: dict[str, dict[str, Any]] = {}
    for name, raw in payloads.items():
        path = output_dir / name
        path.write_bytes(raw)
        declarations[name] = {
            "sha256": _sha256(raw),
            "bytes": len(raw),
            "url": PUBLICATION_EVIDENCE_URLS[name],
        }
    facts = {
        "provider": file_catalog["creator"]["name"],
        "license": file_catalog["license"],
        "official_content_url": content_url,
        "documented_openapi_requires_service_key": True,
        "portal_transport_endpoint_bound_by_ui_definition": True,
    }
    return declarations, facts


def fetch_query(
    *,
    direction: str,
    port_code: str,
    port_name: str,
    start: date,
    end: date,
    row_limit: int,
    timeout: float,
) -> QueryResult:
    opener = _new_opener()
    _request(
        opener,
        urllib.request.Request(PORTMIS_MAIN_URL),
        timeout,
    )
    parameters = _query_parameters(
        direction=direction,
        port_code=port_code,
        port_name=port_name,
        start=start,
        end=end,
        row_limit=row_limit,
    )
    body = _query_body(parameters)
    request = urllib.request.Request(
        PORTMIS_QUERY_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    raw_bytes = _request(opener, request, timeout)
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("PORT-MIS returned a non-JSON query response") from exc
    if payload.get("errorCode"):
        raise RuntimeError(
            "PORT-MIS query error "
            f"{payload.get('errorCode')}: {payload.get('errorMessage', '')}"
        )
    rows = payload.get("dltInOutList") or []
    if not isinstance(rows, list):
        raise RuntimeError("PORT-MIS dltInOutList is not a list")
    total = int(rows[0].get("totalCount", len(rows))) if rows else 0
    if total != len(rows):
        raise RuntimeError(
            f"{direction} query was truncated: returned {len(rows)} of {total}; "
            "use a shorter date window"
        )
    return QueryResult(direction, raw_bytes, rows, total)


def load_query(path: Path, direction: str) -> QueryResult:
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes.decode("utf-8"))
    rows = payload.get("dltInOutList") or []
    total = int(rows[0].get("totalCount", len(rows))) if rows else 0
    if total != len(rows):
        raise RuntimeError(
            f"stored {direction} response is truncated: {len(rows)} of {total}"
        )
    return QueryResult(direction, raw_bytes, rows, total)


def _source_duplicate_count(rows: list[dict[str, Any]]) -> int:
    keys = [
        (*_canonical_call_key(row), _clean(row.get("reqstSeNm")))
        for row in rows
    ]
    return len(keys) - len(set(keys))


def _standardize_calls(
    inbound: QueryResult,
    outbound: QueryResult,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
    duplicate_direction_keys: set[tuple[str, str, str, str]] = set()
    for result in (inbound, outbound):
        for row in result.rows:
            if _clean(row.get("vsslKndCd")) != CONTAINER_SHIP_CODE:
                continue
            if _clean(row.get("reqstSeNm")) != FINAL_DECLARATION:
                continue
            key = _canonical_call_key(row)
            if not all(key):
                continue
            entry = selected.setdefault(key, {})
            prior = entry.get(result.direction)
            if prior is not None:
                duplicate_direction_keys.add(key)
            entry[result.direction] = row

    records: list[dict[str, Any]] = []
    identity_conflict_fields = ("clsgn", "vsslNm", "grtg", "vsslKndCd")
    identity_conflict_calls: set[tuple[str, str, str, str]] = set()
    facility_transitions: Counter[str] = Counter()
    for key, sources in sorted(selected.items()):
        inbound_row = sources.get("inbound", {})
        outbound_row = sources.get("outbound", {})
        if inbound_row and outbound_row:
            for field in identity_conflict_fields:
                left = _clean(inbound_row.get(field))
                right = _clean(outbound_row.get(field))
                if left and right and left != right:
                    identity_conflict_calls.add(key)
        base = inbound_row or outbound_row
        (
            service_facility,
            inbound_facility,
            outbound_facility,
            assignment_basis,
            transition,
        ) = _resolve_service_facility(inbound_row, outbound_row)
        facility_transitions[transition] += 1
        record = {
            "call_id": _call_id(key),
            "port_code": key[0],
            "port_name": _clean(base.get("prtAgNm")),
            "vessel_id": key[1],
            "callsign": _clean(base.get("clsgn")),
            "vessel_name": _clean(base.get("vsslNm")),
            "entry_year": key[2],
            "entry_sequence": key[3],
            "entry_time": _iso_timestamp(
                inbound_row.get("etryptDt") or outbound_row.get("etryptDt")
            ),
            "departure_time": _iso_timestamp(
                outbound_row.get("tkoffDt") or inbound_row.get("tkoffDt")
            ),
            "vessel_kind_code": _clean(base.get("vsslKndCd")),
            "vessel_kind_name": _clean(base.get("vsslKindNm")),
            "gross_tonnage": _number(base.get("grtg")),
            "international_gross_tonnage": _number(base.get("intrlGrtg")),
            "facility_code": service_facility["code"],
            "facility_subcode": service_facility["subcode"],
            "facility_name": service_facility["name"],
            "facility_cluster": service_facility["cluster"],
            "is_terminal_berth": service_facility["is_berth"],
            "exclusion_reason": service_facility["exclusion"],
            "facility_assignment_basis": assignment_basis,
            "inbound_facility_code": inbound_facility["code"],
            "inbound_facility_subcode": inbound_facility["subcode"],
            "inbound_facility_name": inbound_facility["name"],
            "inbound_facility_cluster": inbound_facility["cluster"],
            "outbound_facility_code": outbound_facility["code"],
            "outbound_facility_subcode": outbound_facility["subcode"],
            "outbound_facility_name": outbound_facility["name"],
            "outbound_facility_cluster": outbound_facility["cluster"],
            "previous_port_country": (
                _clean(inbound_row.get("prvsDpmprtNatCd"))
                or _clean(outbound_row.get("prvsDpmprtNatCd"))
            ),
            "previous_port_code": (
                _clean(inbound_row.get("prvsDpmprtPrtCd"))
                or _clean(outbound_row.get("prvsDpmprtPrtCd"))
            ),
            "previous_port_name": (
                _clean(inbound_row.get("prvsDpmprtPrtNm"))
                or _clean(outbound_row.get("prvsDpmprtPrtNm"))
            ),
            "next_port_country": (
                _clean(outbound_row.get("nxlnptNatCd"))
                or _clean(inbound_row.get("nxlnptNatCd"))
            ),
            "next_port_code": (
                _clean(outbound_row.get("nxlnptPrtCd"))
                or _clean(inbound_row.get("nxlnptPrtCd"))
            ),
            "next_port_name": (
                _clean(outbound_row.get("nxlnptPrtNm"))
                or _clean(inbound_row.get("nxlnptPrtNm"))
            ),
            "cargo_class_code": (
                _clean(inbound_row.get("ldadngFrghtClCd"))
                or _clean(outbound_row.get("ldadngFrghtClCd"))
            ),
            "cargo_class_name": (
                _clean(inbound_row.get("ldadngFrghtClNm"))
                or _clean(outbound_row.get("ldadngFrghtClNm"))
            ),
            "inbound_loaded_cargo_tonnage": _number(
                inbound_row.get("ldadngTon")
            ),
            "outbound_loaded_cargo_tonnage": _number(
                outbound_row.get("ldadngTon")
            ),
            "inbound_declaration_type": _clean(inbound_row.get("reqstSeNm")),
            "outbound_declaration_type": _clean(outbound_row.get("reqstSeNm")),
            "inbound_in_query_window": bool(inbound_row),
            "outbound_in_query_window": bool(outbound_row),
        }
        records.append(record)
    return records, {
        "duplicate_direction_keys": len(duplicate_direction_keys),
        "identity_conflict_calls": len(identity_conflict_calls),
        "facility_transition_counts": dict(sorted(facility_transitions.items())),
    }


def _presence_rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(row.get(field) not in (None, "") for row in rows) / len(rows)


def _daily_cycle_metrics(
    primary_calls: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    parsed: list[tuple[datetime, datetime | None]] = []
    for row in primary_calls:
        entry = datetime.fromisoformat(row["entry_time"]) if row["entry_time"] else None
        departure = (
            datetime.fromisoformat(row["departure_time"])
            if row["departure_time"]
            else None
        )
        if entry:
            parsed.append((entry, departure))
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min)
    now = datetime.combine(start, time.min)
    metrics: list[dict[str, Any]] = []
    while now + timedelta(hours=96) <= end_exclusive:
        new_lower = now + timedelta(hours=72)
        new_upper = now + timedelta(hours=96)
        receiving_upper = now + timedelta(hours=72)
        metrics.append(
            {
                "cycle_time": now.isoformat(timespec="minutes"),
                "new_ship_count": sum(
                    new_lower <= entry < new_upper for entry, _departure in parsed
                ),
                "continuing_receiving_count": sum(
                    now <= entry < receiving_upper for entry, _departure in parsed
                ),
                "in_port_count": sum(
                    entry <= now and departure is not None and now < departure
                    for entry, departure in parsed
                ),
            }
        )
        now += timedelta(hours=24)
    return metrics


def build_audit(
    *,
    inbound: QueryResult,
    outbound: QueryResult,
    calls: list[dict[str, Any]],
    primary_cluster: str,
    start: date,
    end: date,
    merge_diagnostics: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inbound_calls = [row for row in calls if row["inbound_in_query_window"]]
    primary_calls = [
        row
        for row in inbound_calls
        if row["facility_cluster"] == primary_cluster
        and row["is_terminal_berth"]
    ]
    entry_times = [
        datetime.fromisoformat(row["entry_time"])
        for row in primary_calls
        if row["entry_time"]
    ]
    stay_hours: list[float] = []
    departure_before_entry = 0
    for row in primary_calls:
        entry = (
            datetime.fromisoformat(row["entry_time"])
            if row["entry_time"]
            else None
        )
        departure = (
            datetime.fromisoformat(row["departure_time"])
            if row["departure_time"]
            else None
        )
        if entry and departure:
            duration = (departure - entry).total_seconds() / 3600
            if duration < 0:
                departure_before_entry += 1
            else:
                stay_hours.append(duration)
    cycle_metrics = _daily_cycle_metrics(primary_calls, start, end)
    new_counts = [row["new_ship_count"] for row in cycle_metrics]
    continuing_counts = [
        row["continuing_receiving_count"] for row in cycle_metrics
    ]
    in_port_counts = [row["in_port_count"] for row in cycle_metrics]
    facilities = Counter(row["facility_name"] for row in primary_calls)
    clusters = Counter(row["facility_cluster"] for row in inbound_calls)
    required_rates = {
        field: _presence_rate(primary_calls, field)
        for field in (
            "callsign",
            "entry_time",
            "departure_time",
            "gross_tonnage",
            "facility_name",
            "previous_port_name",
            "next_port_name",
        )
    }
    invalid_time_rate = (
        (len(primary_calls) - len(entry_times) + departure_before_entry)
        / len(primary_calls)
        if primary_calls
        else 1.0
    )
    median_new = statistics.median(new_counts) if new_counts else 0
    gates = {
        "at_least_100_primary_inbound_calls": len(primary_calls) >= 100,
        "required_fields_at_least_90_percent": (
            min(required_rates.values(), default=0.0) >= 0.90
        ),
        "no_source_business_key_duplicates": (
            _source_duplicate_count(inbound.rows) == 0
            and _source_duplicate_count(outbound.rows) == 0
        ),
        "invalid_time_rate_at_most_5_percent": invalid_time_rate <= 0.05,
        "median_new_ships_per_cycle_at_least_3": median_new >= 3,
        "primary_cluster_has_multiple_berths": len(facilities) >= 2,
        "primary_terminal_mapping_officially_verified": (
            primary_cluster in VERIFIED_TERMINALS
        ),
    }
    audit: dict[str, Any] = {
        "pilot_status": "PASS" if all(gates.values()) else "FAIL",
        "scope": {
            "port_code": inbound.rows[0].get("prtAgCd") if inbound.rows else "",
            "port_name": inbound.rows[0].get("prtAgNm") if inbound.rows else "",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "primary_cluster": primary_cluster,
            "container_ship_code": CONTAINER_SHIP_CODE,
            "declaration_filter": FINAL_DECLARATION,
            "verified_terminal": VERIFIED_TERMINALS.get(primary_cluster),
        },
        "source_counts": {
            "all_inbound_rows": len(inbound.rows),
            "all_outbound_rows": len(outbound.rows),
            "container_calls_union": len(calls),
            "container_inbound_calls": len(inbound_calls),
            "primary_cluster_inbound_calls": len(primary_calls),
            "primary_cluster_unique_vessels": len(
                {row["vessel_id"] for row in primary_calls}
            ),
            "inbound_source_duplicate_rows": _source_duplicate_count(inbound.rows),
            "outbound_source_duplicate_rows": _source_duplicate_count(
                outbound.rows
            ),
            "duplicate_direction_keys": merge_diagnostics[
                "duplicate_direction_keys"
            ],
            "identity_conflict_calls": merge_diagnostics[
                "identity_conflict_calls"
            ],
        },
        "facility_transition_counts": merge_diagnostics[
            "facility_transition_counts"
        ],
        "field_presence_rates": {
            field: round(rate, 6) for field, rate in required_rates.items()
        },
        "time_quality": {
            "departure_before_entry_count": departure_before_entry,
            "invalid_time_rate": round(invalid_time_rate, 6),
            "stay_hours_min": min(stay_hours) if stay_hours else None,
            "stay_hours_median": (
                statistics.median(stay_hours) if stay_hours else None
            ),
            "stay_hours_p95": _percentile(stay_hours, 0.95),
            "stay_hours_max": max(stay_hours) if stay_hours else None,
            "stays_over_72_hours": sum(value > 72 for value in stay_hours),
            "stays_over_168_hours": sum(value > 168 for value in stay_hours),
        },
        "rolling_window_support": {
            "complete_daily_cycles": len(cycle_metrics),
            "new_ships_per_cycle_min": min(new_counts) if new_counts else 0,
            "new_ships_per_cycle_median": median_new,
            "new_ships_per_cycle_max": max(new_counts) if new_counts else 0,
            "continuing_receiving_per_cycle_median": (
                statistics.median(continuing_counts) if continuing_counts else 0
            ),
            "in_port_ships_per_cycle_median": (
                statistics.median(in_port_counts) if in_port_counts else 0
            ),
        },
        "primary_facility_counts": dict(
            sorted(facilities.items(), key=lambda item: (-item[1], item[0]))
        ),
        "container_inbound_cluster_counts": dict(
            sorted(clusters.items(), key=lambda item: (-item[1], item[0]))
        ),
        "gates": gates,
        "limitations": [
            "The JSON transport endpoint is not the documented service-key "
            "OpenAPI. Publication use requires an archived official fileData "
            "record and PORT-MIS UI definition that bind the provider view to "
            "this endpoint.",
            "The primary SINSUNDAE mapping is verified against the Busan Port "
            "Authority; non-primary clusters remain label-derived proxies.",
            "Loaded cargo tonnage is not container moves or terminal throughput.",
            "Next port is a vessel-route field, not a per-container POD.",
            "Forecast trajectories, box attributes, yard state, and bay layout "
            "remain semi-synthetic.",
        ],
    }
    return audit, cycle_metrics


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def _fmt_rate(value: float) -> str:
    return f"{100 * value:.1f}%"


def render_report(
    audit: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    counts = audit["source_counts"]
    time_quality = audit["time_quality"]
    rolling = audit["rolling_window_support"]
    verified_terminal = audit["scope"]["verified_terminal"]
    lines = [
        "# PORT-MIS source snapshot audit",
        "",
        f"Status: **{audit['pilot_status']}**",
        "",
        "This is a bounded acquisition and data-quality audit. It does not "
        "alter the rolling optimization model or its frozen algorithm.",
        f"Publication source contract: "
        f"**{'READY' if manifest.get('publication_ready') else 'PROVISIONAL'}**",
        "",
        "## Scope",
        "",
        f"- Port: {audit['scope']['port_name']} "
        f"({audit['scope']['port_code']})",
        f"- Window: {audit['scope']['start_date']} through "
        f"{audit['scope']['end_date']}",
        f"- Vessel filter: full container ship code "
        f"`{audit['scope']['container_ship_code']}`",
        f"- Primary facility proxy: `{audit['scope']['primary_cluster']}`",
        *(
            [
                f"- Verified terminal: {verified_terminal['terminal_name']}",
                f"- Operator: {verified_terminal['operator']}",
            ]
            if verified_terminal
            else ["- Verified terminal: not yet mapped"]
        ),
        f"- Raw retrieval UTC: {manifest['raw_retrieved_at_utc']}",
        f"- Provenance completion UTC: "
        f"{manifest['provenance_completed_at_utc']}",
        "",
        "## Acquisition and sample size",
        "",
        f"- All inbound rows: {counts['all_inbound_rows']}",
        f"- All outbound rows: {counts['all_outbound_rows']}",
        f"- Container calls in the inbound window: "
        f"{counts['container_inbound_calls']}",
        f"- Primary-cluster inbound calls: "
        f"{counts['primary_cluster_inbound_calls']}",
        f"- Primary-cluster unique vessels: "
        f"{counts['primary_cluster_unique_vessels']}",
        f"- Identity-field conflicts across paired inbound/outbound rows: "
        f"{counts['identity_conflict_calls']}",
        "",
        "## Primary-cluster quality",
        "",
    ]
    for field, rate in audit["field_presence_rates"].items():
        lines.append(f"- `{field}` present: {_fmt_rate(rate)}")
    lines.extend(
        [
            f"- Invalid or reversed time rate: "
            f"{_fmt_rate(time_quality['invalid_time_rate'])}",
            f"- Median port stay: {time_quality['stay_hours_median']:.2f} h"
            if time_quality["stay_hours_median"] is not None
            else "- Median port stay: unavailable",
            f"- 95th-percentile port stay: {time_quality['stay_hours_p95']:.2f} h"
            if time_quality["stay_hours_p95"] is not None
            else "- 95th-percentile port stay: unavailable",
            "",
            "## Rolling-window support",
            "",
            f"- Complete daily cycles: {rolling['complete_daily_cycles']}",
            f"- New ships in each 72--96 h admission slice "
            f"(min/median/max): {rolling['new_ships_per_cycle_min']} / "
            f"{rolling['new_ships_per_cycle_median']} / "
            f"{rolling['new_ships_per_cycle_max']}",
            f"- Median continuing receiving ships in the next 72 h: "
            f"{rolling['continuing_receiving_per_cycle_median']}",
            f"- Median ships physically in port at cycle time: "
            f"{rolling['in_port_ships_per_cycle_median']}",
            "",
            "## Primary facility labels",
            "",
        ]
    )
    for facility, count in audit["primary_facility_counts"].items():
        lines.append(f"- {facility}: {count}")
    lines.extend(["", "## Gates", ""])
    for gate, passed in audit["gates"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{gate}`")
    lines.extend(
        [
            "",
            "## Interpretation and limitations",
            "",
            "The sample is adequate as a real vessel-call and schedule skeleton. "
            "It is not a real yard-allocation benchmark. The Busan Port "
            "Authority identifies Sinsundae as a five-berth container terminal "
            "operated by BPT; all non-primary cluster mappings remain "
            "label-derived until separately verified.",
            "",
            "Calls whose inbound and outbound facilities belong to different "
            "clusters are marked `MULTI_TERMINAL` and excluded from the primary "
            "single-yard proxy.",
            "",
        ]
    )
    for limitation in audit["limitations"]:
        lines.append(f"- {limitation}")
    lines.extend(
        [
            "",
            "Official references:",
            "",
            f"- {OFFICIAL_DATA_PAGE}",
            f"- {OFFICIAL_FILE_PAGE}",
            f"- {BPA_SINSUNDAE_PAGE}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and audit a bounded PORT-MIS public-data pilot"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 7, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 7, 30))
    parser.add_argument("--port-code", default="020")
    parser.add_argument("--port-name", default="부산")
    parser.add_argument("--primary-cluster", default=DEFAULT_PRIMARY_CLUSTER)
    parser.add_argument("--row-limit", type=int, default=50_000)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("local_results/portmis_pilot_2025_07"),
    )
    parser.add_argument(
        "--reuse-raw",
        action="store_true",
        help="Reuse raw_inbound.json and raw_outbound.json in output-dir",
    )
    parser.add_argument(
        "--publication-ready",
        action="store_true",
        help=(
            "Archive and validate official catalogue/UI evidence and emit the "
            "strict publication source contract"
        ),
    )
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--start must be on or before --end")
    if (args.end - args.start).days >= 730:
        parser.error("PORT-MIS public query windows may not exceed 730 days")
    if args.row_limit <= 0 or args.row_limit > 50_000:
        parser.error("--row-limit must be between 1 and 50000")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prior_manifest_path = output_dir / "manifest.json"
    prior_manifest = (
        json.loads(prior_manifest_path.read_text(encoding="utf-8-sig"))
        if args.reuse_raw and prior_manifest_path.exists()
        else {}
    )
    inbound_path = output_dir / "raw_inbound.json"
    outbound_path = output_dir / "raw_outbound.json"
    if args.reuse_raw:
        inbound = load_query(inbound_path, "inbound")
        outbound = load_query(outbound_path, "outbound")
    else:
        inbound = fetch_query(
            direction="inbound",
            port_code=args.port_code,
            port_name=args.port_name,
            start=args.start,
            end=args.end,
            row_limit=args.row_limit,
            timeout=args.timeout,
        )
        outbound = fetch_query(
            direction="outbound",
            port_code=args.port_code,
            port_name=args.port_name,
            start=args.start,
            end=args.end,
            row_limit=args.row_limit,
            timeout=args.timeout,
        )
        inbound_path.write_bytes(inbound.raw_bytes)
        outbound_path.write_bytes(outbound.raw_bytes)

    calls, merge_diagnostics = _standardize_calls(inbound, outbound)
    audit, cycle_metrics = build_audit(
        inbound=inbound,
        outbound=outbound,
        calls=calls,
        primary_cluster=args.primary_cluster,
        start=args.start,
        end=args.end,
        merge_diagnostics=merge_diagnostics,
    )
    primary_calls = [
        row
        for row in calls
        if row["inbound_in_query_window"]
        and row["facility_cluster"] == args.primary_cluster
        and row["is_terminal_berth"]
    ]
    _write_csv(output_dir / "container_calls.csv", calls, STANDARD_FIELDS)
    _write_csv(
        output_dir / "primary_cluster_calls.csv",
        primary_calls,
        STANDARD_FIELDS,
    )
    _write_csv(
        output_dir / "rolling_window_counts.csv",
        cycle_metrics,
        (
            "cycle_time",
            "new_ship_count",
            "continuing_receiving_count",
            "in_port_count",
        ),
    )
    (output_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    now_utc = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    raw_retrieved_at_utc = (
        prior_manifest.get("raw_retrieved_at_utc")
        or prior_manifest.get("retrieved_at_utc")
        or now_utc
    )
    evidence_files: dict[str, dict[str, Any]] = {}
    evidence_facts: dict[str, Any] = {}
    if args.publication_ready:
        evidence_files, evidence_facts = fetch_publication_evidence(
            output_dir,
            timeout=args.timeout,
        )

    request_declarations = {}
    raw_declarations = {}
    for result, path in (
        (inbound, inbound_path),
        (outbound, outbound_path),
    ):
        parameters = _query_parameters(
            direction=result.direction,
            port_code=args.port_code,
            port_name=args.port_name,
            start=args.start,
            end=args.end,
            row_limit=args.row_limit,
        )
        request_body = _query_body(parameters)
        request_declarations[result.direction] = {
            "parameters": parameters,
            "body_sha256": _sha256(request_body),
        }
        raw_declarations[path.name] = {
            "sha256": _sha256(result.raw_bytes),
            "bytes": len(result.raw_bytes),
            "rows": len(result.rows),
            "direction": result.direction,
            "request_body_sha256": _sha256(request_body),
        }
    snapshot_identity = _sha256(
        json.dumps(
            {
                "requests": request_declarations,
                "raw_files": raw_declarations,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    standardized_files = {}
    for name in (
        "container_calls.csv",
        "primary_cluster_calls.csv",
        "rolling_window_counts.csv",
        "audit.json",
    ):
        path = output_dir / name
        standardized_files[name] = {
            "sha256": _sha256(path.read_bytes()),
            "bytes": path.stat().st_size,
        }
    manifest = {
        "schema": (
            PORTMIS_SOURCE_SCHEMA
            if args.publication_ready
            else "portmis-pilot-snapshot-v1"
        ),
        "publication_ready": bool(args.publication_ready),
        "acquisition_mode": (
            PORTMIS_ACQUISITION_MODE
            if args.publication_ready
            else "development_portal_query"
        ),
        "raw_retrieved_at_utc": raw_retrieved_at_utc,
        "provenance_completed_at_utc": now_utc,
        "source_snapshot_sha256": snapshot_identity,
        "official_data_page": OFFICIAL_DATA_PAGE,
        "official_file_page": OFFICIAL_FILE_PAGE,
        "extraction_method": (
            "fixed automated export from the institution-provided PORT-MIS "
            "query page"
            if args.publication_ready
            else "guest PORT-MIS query pilot"
        ),
        "terminal_mapping_sources": {
            "SINSUNDAE": BPA_SINSUNDAE_PAGE,
        },
        "portal_contract": {
            "official_content_url": PORTMIS_MAIN_URL,
            "ui_definition_url": PORTMIS_UI_DEFINITION_URL,
            "transport_url": PORTMIS_QUERY_URL,
            "method": "POST",
            "content_type": "application/json; charset=UTF-8",
            "documented_openapi_used": False,
            "transport_endpoint_status": (
                "bound_to_archived_official_provider_ui"
                if args.publication_ready
                else "pilot_unverified"
            ),
        },
        "pilot_query_url": PORTMIS_QUERY_URL,
        "pilot_only_undocumented_endpoint": not args.publication_ready,
        "query": {
            "port_code": args.port_code,
            "port_name": args.port_name,
            "start_date": args.start.isoformat(),
            "end_date": args.end.isoformat(),
            "row_limit": args.row_limit,
            "directions": request_declarations,
        },
        "raw_files": raw_declarations,
        "standardized_files": standardized_files,
        "official_metadata_files": evidence_files,
        "official_evidence": evidence_facts,
        "source_revision_policy": {
            "archived_bytes_are_immutable": True,
            "provider_corrections_require_new_snapshot": True,
            "live_refetch_hash_is_not_a_reproducibility_requirement": True,
        },
        "data_coverage": {
            "observed_from_portmis": [
                "vessel_call_identity",
                "entry_and_departure_times",
                "berth_or_facility",
                "gross_tonnage",
                "previous_and_next_vessel_ports",
            ],
            "not_observed_from_portmis": [
                "per_call_export_box_volume",
                "per_container_discharge_port",
                "container_size_and_height",
                "historical_booking_forecasts",
                "yard_inventory_and_bay_layout",
                "legacy_yard_allocation",
            ],
            "treatment": {
                "schedule_and_vessel_skeleton": "observed",
                "box_demand": "capacity-anchored semi-synthetic calibration",
                "box_attributes": "semi-synthetic integer disaggregation",
                "forecast_trajectories": "controlled semi-synthetic errors",
                "yard_state_and_layout": "controlled semi-synthetic generator",
            },
        },
        "derived_files": [
            "container_calls.csv",
            "primary_cluster_calls.csv",
            "rolling_window_counts.csv",
            "audit.json",
            "report.md",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        render_report(audit, manifest),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": audit["pilot_status"],
                "output_dir": str(output_dir),
                "primary_cluster_calls": audit["source_counts"][
                    "primary_cluster_inbound_calls"
                ],
                "complete_cycles": audit["rolling_window_support"][
                    "complete_daily_cycles"
                ],
                "gates": audit["gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit["pilot_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

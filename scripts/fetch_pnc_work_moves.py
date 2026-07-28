"""Archive and standardize public PNC berth-schedule work quantities.

The PNC site uses a POST form protected by Cloudflare. This script delegates
HTTP transport to curl, archives the returned HTML, and parses the operator's
published discharge/loading quantities without modifying them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


PNC_SCHEDULE_URL = "https://svc.pncport.com/info/CMS/Ship/Info.pnc?mCode=MN014"
PNC_HOME = "https://www.pncport.com/"
PERIODS = {
    "2026_03": ("20260301", "20260331"),
    "2026_04": ("20260401", "20260430"),
    "2026_05": ("20260501", "20260531"),
    "2026_06": ("20260601", "20260630"),
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
)
COLUMNS = [
    "source_row",
    "vessel_name",
    "vessel_code",
    "carrier_voyage",
    "operator",
    "route",
    "berth_direction",
    "berth_time",
    "departure_time",
    "berth",
    "gate_cutoff",
    "discharge_quantity",
    "load_quantity",
    "shift_quantity",
    "mooring_company",
    "documents",
    "updated_time",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def curl_fetch(start: str, end: str, output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="pnc_schedule_") as temp_dir:
        cookie = Path(temp_dir) / "cookies.txt"
        common = [
            "curl.exe",
            "-L",
            "-sS",
            "--fail",
            "-A",
            USER_AGENT,
        ]
        subprocess.run(
            [
                *common,
                "-c",
                str(cookie),
                "-e",
                PNC_HOME,
                PNC_SCHEDULE_URL,
                "-o",
                "NUL",
            ],
            check=True,
        )
        subprocess.run(
            [
                *common,
                "-b",
                str(cookie),
                "-c",
                str(cookie),
                "-e",
                PNC_SCHEDULE_URL,
                "-X",
                "POST",
                "--data-urlencode",
                f"STARTDATE={start}",
                "--data-urlencode",
                f"ENDDATE={end}",
                "--data-urlencode",
                "ROUTE=",
                "--data-urlencode",
                "OPERATOR=",
                "--data-urlencode",
                "ROWCOUNT=500",
                PNC_SCHEDULE_URL,
                "-o",
                str(output),
            ],
            check=True,
        )


def parse_schedule(path: Path, period: str) -> pd.DataFrame:
    tables = pd.read_html(path)
    if len(tables) != 1 or len(tables[0].columns) != len(COLUMNS):
        raise ValueError(f"Unexpected PNC schedule table structure in {path}")
    frame = tables[0].copy()
    frame.columns = COLUMNS
    frame["period"] = period
    for column in ("berth_time", "departure_time", "gate_cutoff", "updated_time"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in ("discharge_quantity", "load_quantity", "shift_quantity"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def build(output_root: Path, reuse_raw: bool = False) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    frames = []
    raw_rows = []
    for period, (start, end) in PERIODS.items():
        raw_path = output_root / f"raw_schedule_{period}.html"
        if not reuse_raw or not raw_path.exists():
            curl_fetch(start, end, raw_path)
        frame = parse_schedule(raw_path, period)
        frames.append(frame)
        raw_rows.append(
            {
                "period": period,
                "start": start,
                "end": end,
                "url": PNC_SCHEDULE_URL,
                "method": "POST",
                "rows": len(frame),
                "bytes": raw_path.stat().st_size,
                "sha256": sha256(raw_path),
            }
        )

    schedule = pd.concat(frames, ignore_index=True)
    schedule.to_csv(
        output_root / "pnc_operator_schedule.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(raw_rows).to_csv(
        output_root / "raw_source_manifest.csv",
        index=False,
        encoding="utf-8-sig",
    )
    audit = {
        "status": "PASS",
        "source": PNC_SCHEDULE_URL,
        "periods": list(PERIODS),
        "rows": len(schedule),
        "missing_berth_time": int(schedule["berth_time"].isna().sum()),
        "missing_departure_time": int(schedule["departure_time"].isna().sum()),
        "missing_load_quantity": int(schedule["load_quantity"].isna().sum()),
        "missing_discharge_quantity": int(
            schedule["discharge_quantity"].isna().sum()
        ),
        "negative_load_quantity": int((schedule["load_quantity"] < 0).sum()),
        "negative_discharge_quantity": int(
            (schedule["discharge_quantity"] < 0).sum()
        ),
        "interpretation": (
            "PNC operator-published container work quantities; historical "
            "rows may include zero-quantity calls"
        ),
    }
    if any(
        audit[key]
        for key in (
            "missing_berth_time",
            "missing_departure_time",
            "missing_load_quantity",
            "missing_discharge_quantity",
            "negative_load_quantity",
            "negative_discharge_quantity",
        )
    ):
        audit["status"] = "REVIEW"
    (output_root / "source_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {
        "protocol_version": "pnc-operator-work-moves-v1",
        "created_by": "scripts/fetch_pnc_work_moves.py",
        "source": PNC_SCHEDULE_URL,
        "query_method": "public POST form via curl transport",
        "outputs": {
            filename: {
                "bytes": (output_root / filename).stat().st_size,
                "sha256": sha256(output_root / filename),
            }
            for filename in (
                "pnc_operator_schedule.csv",
                "raw_source_manifest.csv",
                "source_audit.json",
            )
        },
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/pnc_operator_work_moves"
        ),
    )
    parser.add_argument("--reuse-raw", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.output_root, args.reuse_raw), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

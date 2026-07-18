"""Summarize experiment CSV files without mandatory statistical dependencies."""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict

SCENARIO_FIELDS = (
    "instance",
    "initial_utilization",
    "forecast_error",
    "forecast_error_mode",
    "outbound_rate",
    "time_limit",
)
DEFAULT_METRICS = (
    "total_wall_time",
    "realized_unplaced",
    "stability_cost",
    "mean_realized_bays_per_ship_pod",
)


def _number(row: dict, field: str) -> float | None:
    try:
        value = row.get(field, "")
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def describe(values: list[float]) -> dict[str, float | int | None]:
    """Return deterministic descriptive statistics and a normal 95% CI."""
    if not values:
        return {"count": 0, "mean": None, "std": None, "median": None, "ci95": None}
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    ci95 = 1.96 * std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "count": len(values),
        "mean": mean,
        "std": std,
        "median": statistics.median(values),
        "ci95": ci95,
    }


def paired_comparison(
    rows: list[dict],
    metric: str,
    left: str,
    right: str,
) -> dict:
    """Compare configurations on identical scenario and seed keys."""
    indexed = {}
    for row in rows:
        value = _number(row, metric)
        if value is None:
            continue
        key = tuple(row.get(field) for field in SCENARIO_FIELDS) + (row.get("seed"),)
        indexed[key, row.get("configuration")] = value
    differences = [
        indexed[key, left] - indexed[key, right]
        for key, configuration in sorted(indexed)
        if configuration == left and (key, right) in indexed
    ]
    result = {
        "left": left,
        "right": right,
        "metric": metric,
        "difference_definition": "left - right",
        "differences": differences,
        "summary": describe(differences),
        "wilcoxon": None,
        "wilcoxon_note": "scipy unavailable; pure-Python paired statistics reported",
    }
    try:
        from scipy.stats import wilcoxon  # type: ignore

        if differences and any(abs(value) > 1e-12 for value in differences):
            statistic, p_value = wilcoxon(differences)
            result["wilcoxon"] = {"statistic": float(statistic), "p_value": float(p_value)}
            result["wilcoxon_note"] = "two-sided scipy Wilcoxon signed-rank test"
    except ImportError:
        pass
    return result


def summarize(rows: list[dict], metrics: tuple[str, ...]) -> dict:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in SCENARIO_FIELDS) + (
            row.get("configuration"),
        )
        grouped[key].append(row)
    summaries = []
    for key, group in sorted(grouped.items()):
        entry = {field: value for field, value in zip(SCENARIO_FIELDS, key[:-1])}
        entry["configuration"] = key[-1]
        entry["metrics"] = {
            metric: describe([
                value for row in group if (value := _number(row, metric)) is not None
            ])
            for metric in metrics
        }
        summaries.append(entry)
    comparisons = [
        paired_comparison(rows, metric, left, right)
        for metric in metrics
        for left, right in (("full", "full_direct"), ("full", "core_start"))
    ]
    return {"group_summaries": summaries, "paired_comparisons": comparisons}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--metrics", nargs="+", default=list(DEFAULT_METRICS))
    parser.add_argument("--output")
    args = parser.parse_args()
    with open(args.input, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    result = summarize(rows, tuple(args.metrics))
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

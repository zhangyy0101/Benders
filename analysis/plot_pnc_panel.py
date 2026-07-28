"""Create publication-ready figures for the verified PNC vessel-call panel."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter


BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
SKY = "#56B4E9"
GRAY = "#6B7280"
GRID = "#D1D5DB"
MONTH_LABELS = {
    "2026_03": "Mar",
    "2026_04": "Apr",
    "2026_05": "May",
    "2026_06": "Jun",
}
BERTH_COLORS = {
    "B1": BLUE,
    "B2": ORANGE,
    "B3": GREEN,
    "B4": PURPLE,
    "B5": SKY,
}


def set_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#374151",
            "axes.linewidth": 0.7,
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "grid.alpha": 0.7,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf")
    fig.savefig(output_dir / f"{stem}.png", dpi=400)
    plt.close(fig)


def monthly_profile(monthly: pd.DataFrame, output_dir: Path) -> None:
    monthly = monthly.copy()
    monthly["label"] = monthly["period"].map(MONTH_LABELS)
    colors = [GREEN if period == "2026_05" else BLUE for period in monthly["period"]]
    x = np.arange(len(monthly))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8))

    ax = axes[0]
    width = 0.36
    calls = ax.bar(
        x - width / 2, monthly["calls"], width=width, color=colors, label="Calls"
    )
    vessels = ax.bar(
        x + width / 2,
        monthly["unique_vessels"],
        width=width,
        color=[GRAY] * len(monthly),
        label="Unique vessels",
    )
    ax.set_xticks(x, monthly["label"])
    ax.set_ylabel("Count")
    ax.set_ylim(0, max(monthly["calls"]) * 1.2)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.set_title("(a) Monthly panel size")
    ax.legend(frameon=False, ncol=2, loc="upper center")
    for bars in (calls, vessels):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 2,
                f"{bar.get_height():.0f}",
                ha="center",
                va="bottom",
                fontsize=7,
            )

    ax = axes[1]
    bars = ax.bar(x, monthly["median_stay_hours"], color=colors, width=0.62)
    ax.set_xticks(x, monthly["label"])
    ax.set_ylabel("Median port stay (hours)")
    ax.set_ylim(0, max(monthly["median_stay_hours"]) * 1.24)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.set_title("(b) Vessel stay duration")
    for bar, value in zip(bars, monthly["median_stay_hours"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.7,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.text(
        0.98,
        0.96,
        "Green: primary panel",
        transform=ax.transAxes,
        ha="right",
        va="top",
        color=GREEN,
        fontsize=8,
    )
    fig.subplots_adjust(wspace=0.32)
    save(fig, output_dir, "pnc_fig1_monthly_profile")


def daily_arrivals(daily: pd.DataFrame, output_dir: Path) -> None:
    daily = daily.copy()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["rolling_7d"] = daily["arrivals"].rolling(7, center=True, min_periods=1).mean()

    fig, ax = plt.subplots(figsize=(7.2, 2.8))
    may_start = pd.Timestamp("2026-05-01")
    may_end = pd.Timestamp("2026-06-01")
    ax.axvspan(may_start, may_end, color=GREEN, alpha=0.10, label="Primary panel (May)")
    ax.plot(daily["date"], daily["arrivals"], color=SKY, linewidth=0.8, alpha=0.8)
    ax.plot(
        daily["date"],
        daily["rolling_7d"],
        color=BLUE,
        linewidth=1.8,
        label="7-day mean",
    )
    ax.set_ylabel("PNC vessel arrivals per day")
    ax.set_xlabel("2026")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.set_title("Daily PNC vessel-call density, March–June 2026")
    ax.legend(frameon=False, ncol=2, loc="upper right")
    save(fig, output_dir, "pnc_fig2_daily_arrivals")


def berth_and_scale(
    berth: pd.DataFrame, calls: pd.DataFrame, output_dir: Path
) -> None:
    berth_matrix = (
        berth.pivot(index="period", columns="berth", values="share_within_period")
        .reindex(index=MONTH_LABELS, columns=BERTH_COLORS)
        .fillna(0)
    )
    berth_matrix.index = [MONTH_LABELS[value] for value in berth_matrix.index]
    berth_matrix.reset_index().to_csv(
        output_dir / "pnc_fig3_berth_shares.csv", index=False, encoding="utf-8-sig"
    )

    primary = calls.loc[calls["period"] == "2026_05"].copy()
    primary[["call_id", "berth", "gross_tonnage", "stay_hours"]].to_csv(
        output_dir / "pnc_fig3_primary_scale_stay.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.15))
    ax = axes[0]
    image = ax.imshow(
        berth_matrix.to_numpy(),
        aspect="auto",
        cmap="Blues",
        vmin=0,
        vmax=max(0.25, berth_matrix.to_numpy().max()),
    )
    ax.set_xticks(np.arange(len(berth_matrix.columns)), berth_matrix.columns)
    ax.set_yticks(np.arange(len(berth_matrix.index)), berth_matrix.index)
    ax.set_xlabel("PNC berth")
    ax.set_ylabel("Month")
    ax.set_title("(a) Berth distribution")
    for row in range(berth_matrix.shape[0]):
        for column in range(berth_matrix.shape[1]):
            value = berth_matrix.iloc[row, column]
            ax.text(
                column,
                row,
                f"{value:.0%}",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if value > 0.22 else "#111827",
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1.0))

    ax = axes[1]
    for berth_name, group in primary.groupby("berth"):
        ax.scatter(
            group["gross_tonnage"] / 1000,
            group["stay_hours"],
            s=18,
            alpha=0.68,
            color=BERTH_COLORS[berth_name],
            label=berth_name,
            edgecolors="none",
        )
    ax.set_xlabel("Gross tonnage (thousand GT)")
    ax.set_ylabel("Port stay (hours)")
    ax.set_title("(b) Primary-panel vessel scale and stay")
    ax.grid()
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    fig.subplots_adjust(wspace=0.38)
    save(fig, output_dir, "pnc_fig3_berth_and_vessel_scale")


def write_captions(output_dir: Path) -> None:
    text = """# Suggested PNC figure captions

## PNC Figure 1

Monthly characteristics of the verified PNC vessel-call panels. May 2026 is
selected as the primary panel because it aligns temporally with the Yangshan
observations while satisfying all source-quality and five-berth coverage
gates. March, April, and June are retained for temporal robustness.

## PNC Figure 2

Daily observed vessel arrivals at PNC from March through June 2026. The line
shows a centered seven-day mean and the shaded region identifies the May
primary panel. Zero-arrival days are retained in the calendar sequence.

## PNC Figure 3

PNC berth use and vessel characteristics. Panel (a) reports monthly shares of
calls across the five verified PNC berths. Panel (b) relates observed gross
tonnage to port-stay duration for the May primary panel. Gross tonnage is used
only as a vessel-scale descriptor and is not converted into container counts.
"""
    (output_dir / "pnc_figure_captions.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("local_results/protocol_v2_pnc_yangshan/pnc_formal_panel"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("local_results/protocol_v2_pnc_yangshan/figures/pnc_panel"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_style()
    monthly = pd.read_csv(args.input_dir / "monthly_summary.csv")
    daily = pd.read_csv(args.input_dir / "daily_arrivals.csv")
    berth = pd.read_csv(args.input_dir / "berth_distribution.csv")
    calls = pd.read_csv(args.input_dir / "pnc_calls_all.csv")
    monthly_profile(monthly, args.output_dir)
    daily_arrivals(daily, args.output_dir)
    berth_and_scale(berth, calls, args.output_dir)
    write_captions(args.output_dir)
    print(f"Wrote PNC publication figures to {args.output_dir}")


if __name__ == "__main__":
    main()

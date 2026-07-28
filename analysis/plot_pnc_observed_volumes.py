"""Plot the observed PNC call-volume layer and matching diagnostics."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
GRAY = "#6B7280"
GRID = "#D1D5DB"


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


def volume_figure(
    monthly: pd.DataFrame, calls: pd.DataFrame, output_dir: Path
) -> None:
    periods = monthly["period"].tolist()
    labels = [item.replace("2026_", "") for item in periods]
    x = np.arange(len(periods))
    plot_monthly = monthly[
        ["period", "pnc_calls", "export_calls", "observed_export_boxes"]
    ].copy()
    plot_monthly.to_csv(
        output_dir / "volume_fig1_monthly_data.csv",
        index=False,
        encoding="utf-8-sig",
    )
    calls[
        ["period", "call_id", "observed_export_boxes", "portmis_validated"]
    ].to_csv(
        output_dir / "volume_fig1_call_data.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    ax = axes[0]
    bars = ax.bar(
        x, monthly["observed_export_boxes"] / 1000, 0.58, color=BLUE
    )
    ax.set_xticks(x, labels)
    ax.set_xlabel("Month in 2026")
    ax.set_ylabel("Observed export boxes (thousand)")
    ax.set_title("(a) PNC-published export volume")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    for bar, value in zip(bars, monthly["export_calls"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.2,
            f"{int(value)} calls",
            ha="center",
            va="bottom",
            fontsize=8,
            color=GRAY,
        )

    ax = axes[1]
    distributions = [
        calls.loc[calls["period"] == period, "observed_export_boxes"].to_numpy()
        for period in periods
    ]
    plot = ax.boxplot(
        distributions,
        tick_labels=labels,
        patch_artist=True,
        showfliers=False,
        widths=0.58,
        medianprops={"color": "#111827", "linewidth": 1.2},
        whiskerprops={"color": GRAY},
        capprops={"color": GRAY},
    )
    for patch in plot["boxes"]:
        patch.set_facecolor(GREEN)
        patch.set_alpha(0.85)
    ax.set_xlabel("Month in 2026")
    ax.set_ylabel("Observed export boxes per call")
    ax.set_title("(b) Positive export-call distribution")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    fig.subplots_adjust(wspace=0.34)
    save(fig, output_dir, "volume_fig1_observed_work")


def matching_figure(calls: pd.DataFrame, output_dir: Path) -> None:
    diagnostics = calls.loc[calls["portmis_validated"]].copy()[
        [
            "period",
            "call_id",
            "port_entry_to_berth_hours",
            "departure_error_hours",
            "match_score_hours",
        ]
    ].copy()
    diagnostics.to_csv(
        output_dir / "volume_fig2_matching_data.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    ax = axes[0]
    validated = calls.loc[calls["portmis_validated"]].copy()
    errors = np.sort(validated["departure_error_hours"].to_numpy())
    cumulative = np.arange(1, len(errors) + 1) / len(errors)
    ax.step(errors, cumulative * 100, where="post", color=BLUE, linewidth=1.6)
    ax.axvline(
        validated["departure_error_hours"].quantile(0.95),
        color=ORANGE,
        linestyle="--",
        linewidth=1.2,
        label="95th percentile",
    )
    ax.set_xscale("symlog", linthresh=0.05)
    ax.set_xlabel("Absolute departure-time error (h)")
    ax.set_ylabel("Cumulative matched calls (%)")
    ax.set_title("(a) Departure-time agreement")
    ax.grid()
    ax.set_axisbelow(True)
    ax.legend(frameon=False)

    ax = axes[1]
    ax.scatter(
        validated["port_entry_to_berth_hours"],
        validated["departure_error_hours"],
        s=16,
        color=GREEN,
        alpha=0.65,
        edgecolors="none",
    )
    ax.set_xlabel("PNC berth time minus PORT-MIS entry (h)")
    ax.set_ylabel("Absolute departure-time error (h)")
    ax.set_title("(b) One-to-one match diagnostics")
    ax.grid()
    ax.set_axisbelow(True)
    save(fig, output_dir, "volume_fig2_matching_quality")


def write_captions(output_dir: Path) -> None:
    text = """# Suggested figure captions

## Volume Figure 1

Observed export-container demand at PNC for the March--June 2026 vessel-call
panels. Panel (a) aggregates the loading quantities published in PNC's berth
schedule and labels the number of positive export calls. Panel (b) shows their
call-level distributions. PNC loading quantity is the formal export-demand
anchor; discharge quantities do not enter the model.

## Volume Figure 2

Independent quality diagnostics for matching PORT-MIS vessel calls to the
PNC-primary panel. Matching uses exact normalized vessel names and minimizes
the combined entry/berth and departure-time discrepancy. All 428 PORT-MIS
calls are matched one-to-one; the 95th percentile absolute departure-time
error is 0.23 hours. Unmatched PNC rows remain in the primary source panel.
"""
    (output_dir / "volume_figure_captions.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/pnc_observed_call_volumes"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/figures/"
            "pnc_observed_call_volumes"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_style()
    monthly = pd.read_csv(args.input_dir / "monthly_pnc_export_summary.csv")
    all_calls = pd.read_csv(args.input_dir / "pnc_calls_all.csv")
    export_calls = pd.read_csv(args.input_dir / "pnc_export_calls.csv")
    volume_figure(monthly, export_calls, args.output_dir)
    matching_figure(all_calls, args.output_dir)
    write_captions(args.output_dir)
    print(f"Wrote observed-volume figures to {args.output_dir}")


if __name__ == "__main__":
    main()

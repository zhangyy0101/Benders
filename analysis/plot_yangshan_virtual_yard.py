"""Publication figures for the OF-filtered Yangshan virtual yard."""

from __future__ import annotations

import argparse
import json
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
            "grid.color": GRID,
            "grid.linewidth": 0.5,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
        }
    )


def save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf")
    fig.savefig(output_dir / f"{stem}.png", dpi=400)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--yard-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/"
            "yangshan_calibrated_virtual_yard"
        ),
    )
    parser.add_argument(
        "--calibration-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/"
            "yangshan_observed_calibration"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/figures/virtual_yard"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_style()

    snapshots = pd.read_csv(args.calibration_root / "yard_calibration.csv")
    diagnostics = pd.read_csv(args.yard_root / "yard_pressure_diagnostics.csv")
    audit = json.loads((args.yard_root / "yard_audit.json").read_text())
    snapshots.to_csv(
        args.output_dir / "yard_fig1_snapshot_data.csv",
        index=False,
        encoding="utf-8-sig",
    )
    diagnostics.to_csv(
        args.output_dir / "yard_fig1_pressure_data.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.0))
    labels = ["05-08", "05-19", "05-25"]
    x = np.arange(3)
    ax = axes[0]
    bars = ax.bar(
        x,
        snapshots["slot_rows"] / 1000,
        0.58,
        color=BLUE,
        alpha=0.88,
    )
    ax.set_xticks(x, labels)
    ax.set_ylabel("Export-capable slot rows (thousand)")
    ax.set_title("(a) OF-filtered Yangshan snapshots")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    for bar, areas, occupied in zip(
        bars, snapshots["areas"], snapshots["occupied_slot_share"]
    ):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.25,
            f"{int(areas)} areas",
            ha="center",
            fontsize=8,
            color=GRAY,
        )
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() * 0.52,
            f"{occupied:.1%}\noccupied",
            ha="center",
            va="center",
            fontsize=8,
            color="white",
        )

    ax = axes[1]
    profile_order = ["capacity_relief_080", "observed_full", "high_pressure"]
    profile_labels = ["Capacity\nrelief", "Observed\nOF scale", "High\nutilization"]
    maxima = (
        diagnostics.groupby("yard_profile")["dynamic_peak_load_ratio"]
        .max()
        .reindex(profile_order)
    )
    colors = [GREEN, BLUE, ORANGE]
    bars = ax.bar(np.arange(3), maxima, 0.58, color=colors)
    ax.set_xticks(np.arange(3), profile_labels)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("Maximum dynamic load ratio")
    ax.set_title("(b) Demand-linked yard profiles")
    ax.axhline(1.0, color=GRAY, linestyle="--", linewidth=1)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    for bar, value in zip(bars, maxima):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.018,
            f"{value:.3f}",
            ha="center",
            fontsize=8,
        )
    fig.subplots_adjust(wspace=0.34)
    save(fig, args.output_dir, "yard_fig1_of_scope_pressure")

    captions = """# Suggested figure caption

## Yard Figure 1

OF-filtered Yangshan yard calibration and demand-linked virtual-yard profiles.
Panel (a) reports only areas whose function list contains OF; bars show
export-capable slot rows and the line shows snapshot occupancy. Panel (b)
reports the maximum conservative size-specific load ratio when PNC export
boxes occupy capacity from the start of the 72-hour receiving window until
departure. The observed-scale profile is the baseline; the other profiles are
controlled capacity sensitivities rather than physical PNC layouts.
"""
    (args.output_dir / "yard_figure_captions.md").write_text(
        captions, encoding="utf-8"
    )
    print(f"Wrote virtual-yard figures to {args.output_dir}")


if __name__ == "__main__":
    main()

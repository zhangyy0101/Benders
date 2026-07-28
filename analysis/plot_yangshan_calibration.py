"""Create publication-ready figures for the Yangshan calibration layer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter


BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
SKY = "#56B4E9"
GRAY = "#6B7280"
GRID = "#D1D5DB"
GROUP_ORDER = ("20-STD", "20-HIGH", "40-STD", "40-HIGH")
GROUP_COLORS = {
    "20-STD": SKY,
    "20-HIGH": BLUE,
    "40-STD": "#E69F00",
    "40-HIGH": ORANGE,
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


def save_figure(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    fig.savefig(output_dir / f"{stem}.pdf")
    fig.savefig(output_dir / f"{stem}.png", dpi=400)
    plt.close(fig)


def load_distribution(path: Path, label: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["group"] = (
        frame["size_ft"].astype(int).astype(str)
        + "-"
        + frame["height_class"].astype(str)
    )
    frame["dataset"] = label
    return frame


def snapshot_profile(yard: pd.DataFrame, output_dir: Path) -> None:
    yard = yard.copy()
    yard["date"] = yard["snapshot"].map(
        {"0508": "May 8", "0519": "May 19", "0525": "May 25"}
    )
    x = np.arange(len(yard))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.65))

    ax = axes[0]
    bars = ax.bar(x, yard["occupied_slot_share"], color=[BLUE, BLUE, GREEN], width=0.62)
    ax.set_xticks(x, yard["date"])
    ax.set_ylabel("Occupied slot-row share")
    ax.set_ylim(0, 0.65)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.set_title("(a) Yard utilization")
    for bar, value in zip(bars, yard["occupied_slot_share"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.012,
            f"{value:.1%}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax = axes[1]
    bars = ax.bar(
        x,
        yard["model_compatible_export_union"] / 1000,
        color=[BLUE, BLUE, GREEN],
        width=0.62,
    )
    ax.set_xticks(x, yard["date"])
    ax.set_ylabel("Unique export containers (thousand)")
    ax.set_ylim(0, max(yard["model_compatible_export_union"] / 1000) * 1.18)
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.set_title("(b) Model-compatible evidence")
    for bar, value in zip(bars, yard["model_compatible_export_union"]):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.6,
            f"{value:,}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    fig.subplots_adjust(wspace=0.34)
    save_figure(fig, output_dir, "fig1_yangshan_snapshot_profile")


def temporal_validation(
    calibration: pd.DataFrame,
    validation: pd.DataFrame,
    metrics: dict[str, object],
    output_dir: Path,
) -> None:
    combined = pd.concat([calibration, validation], ignore_index=True)
    mix = (
        combined.groupby(["dataset", "group"])["observed_containers"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=GROUP_ORDER, fill_value=0)
    )
    mix = mix.div(mix.sum(axis=1), axis=0)

    top_pods = (
        calibration.groupby("pod")["observed_containers"]
        .sum()
        .nlargest(12)
        .index
    )
    pod = (
        combined.loc[combined["pod"].isin(top_pods)]
        .groupby(["pod", "dataset"])["observed_containers"]
        .sum()
        .unstack(fill_value=0)
    )
    totals = combined.groupby("dataset")["observed_containers"].sum()
    pod = pod.div(totals, axis=1).loc[top_pods]

    mix.reset_index().to_csv(
        output_dir / "fig2_size_height_mix.csv", index=False, encoding="utf-8-sig"
    )
    pod.reset_index().to_csv(
        output_dir / "fig2_top_pod_shares.csv", index=False, encoding="utf-8-sig"
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.25))
    ax = axes[0]
    x = np.arange(len(mix))
    bottom = np.zeros(len(mix))
    for group in GROUP_ORDER:
        values = mix[group].to_numpy()
        ax.bar(
            x,
            values,
            bottom=bottom,
            label=group,
            color=GROUP_COLORS[group],
            width=0.58,
        )
        bottom += values
    ax.set_xticks(x, ["Calibration\n(May 8 & 19)", "Held-out\n(May 25)"])
    ax.set_ylabel("Share of containers")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_title("(a) Size–height composition")
    ax.legend(frameon=False, ncol=2, loc="lower center")

    ax = axes[1]
    y = np.arange(len(pod))
    ax.scatter(pod["Calibration"], y, color=BLUE, s=24, label="Calibration", zorder=3)
    ax.scatter(pod["Held-out"], y, color=GREEN, s=24, marker="s", label="Held-out", zorder=3)
    for index in range(len(pod)):
        ax.plot(
            [pod["Calibration"].iloc[index], pod["Held-out"].iloc[index]],
            [index, index],
            color=GRID,
            linewidth=1,
            zorder=1,
        )
    ax.set_yticks(y, pod.index)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_xlabel("Share of containers")
    ax.set_title("(b) Leading discharge ports")
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right")
    ax.text(
        0.02,
        0.98,
        f"POD TV distance = {metrics['pod_total_variation_distance']:.3f}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        color=GRAY,
        fontsize=8,
    )
    fig.subplots_adjust(wspace=0.42)
    save_figure(fig, output_dir, "fig2_temporal_validation")


def joint_heatmap(
    calibration: pd.DataFrame, validation: pd.DataFrame, output_dir: Path
) -> None:
    top_pods = (
        calibration.groupby("pod")["observed_containers"]
        .sum()
        .nlargest(15)
        .index
    )

    matrices = []
    for frame in (calibration, validation):
        matrix = (
            frame.loc[frame["pod"].isin(top_pods)]
            .pivot_table(
                index="pod",
                columns="group",
                values="observed_containers",
                aggfunc="sum",
                fill_value=0,
            )
            .reindex(index=top_pods, columns=GROUP_ORDER, fill_value=0)
        )
        matrix = matrix / frame["observed_containers"].sum() * 100
        matrices.append(matrix)
    vmax = max(matrix.to_numpy().max() for matrix in matrices)

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.7), sharey=True)
    image = None
    for ax, matrix, title in zip(
        axes, matrices, ("(a) Calibration", "(b) Held-out validation")
    ):
        image = ax.imshow(
            matrix.to_numpy(),
            aspect="auto",
            cmap="Blues",
            vmin=0,
            vmax=vmax,
            interpolation="nearest",
        )
        ax.set_xticks(np.arange(len(GROUP_ORDER)), GROUP_ORDER, rotation=35, ha="right")
        ax.set_yticks(np.arange(len(top_pods)), top_pods)
        ax.set_title(title)
        ax.set_xlabel("Size–height group")
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = matrix.iloc[row, column]
                if value >= 0.15:
                    ax.text(
                        column,
                        row,
                        f"{value:.1f}",
                        ha="center",
                        va="center",
                        fontsize=6.5,
                        color="white" if value > vmax * 0.52 else "#111827",
                    )
    axes[0].set_ylabel("Discharge port")
    colorbar = fig.colorbar(image, ax=axes, fraction=0.025, pad=0.03)
    colorbar.set_label("Share of all containers (%)")
    fig.subplots_adjust(wspace=0.12, right=0.88)
    save_figure(fig, output_dir, "fig3_joint_distribution_heatmap")


def write_captions(output_dir: Path) -> None:
    text = """# Suggested figure captions

## Figure 1

Yangshan snapshot characteristics. Panel (a) reports occupied slot rows as a
share of all recorded yard slot rows. Panel (b) reports unique, deduplicated
export containers compatible with the optimization model. May 8 and May 19
form the calibration sample; May 25 is held out for temporal validation.

## Figure 2

Temporal validation of the Yangshan observation-based calibration. Panel (a)
compares the joint size–height composition between the calibration and held-out
samples. Panel (b) compares shares of the twelve leading calibration-sample
discharge ports. Container size and height remain stable, whereas POD shares
exhibit greater temporal variation.

## Figure 3

Observed joint POD–size–height distributions in the calibration and held-out
Yangshan samples. Cells report percentages of all model-compatible export
containers in the corresponding sample. The common color scale permits direct
comparison across panels.
"""
    (output_dir / "figure_captions.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/yangshan_observed_calibration"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/figures/yangshan_calibration"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_style()

    yard = pd.read_csv(args.input_dir / "yard_calibration.csv", dtype={"snapshot": str})
    calibration = load_distribution(
        args.input_dir / "observed_joint_distribution.csv", "Calibration"
    )
    validation = load_distribution(
        args.input_dir / "heldout_joint_distribution.csv", "Held-out"
    )
    metrics = json.loads(
        (args.input_dir / "temporal_validation.json").read_text(encoding="utf-8")
    )

    snapshot_profile(yard, args.output_dir)
    temporal_validation(calibration, validation, metrics, args.output_dir)
    joint_heatmap(calibration, validation, args.output_dir)
    write_captions(args.output_dir)
    print(f"Wrote publication figures to {args.output_dir}")


if __name__ == "__main__":
    main()

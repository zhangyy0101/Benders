"""Publication figures for PNC--Yangshan export-attribute generation."""

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


def marginal_figure(
    groups: pd.DataFrame,
    calibration: pd.DataFrame,
    heldout: pd.DataFrame,
    output_dir: Path,
) -> None:
    generated = (
        groups.groupby(["pod", "size_ft", "height_class"])["boxes"].sum()
        / groups["boxes"].sum()
    )
    generated = generated.rename("generated").reset_index()
    joint = calibration.merge(
        generated,
        on=["pod", "size_ft", "height_class"],
        how="outer",
    ).fillna(0)
    joint.to_csv(
        output_dir / "attribute_fig1_joint_data.csv",
        index=False,
        encoding="utf-8-sig",
    )

    cal_pod = calibration.groupby("pod")["probability"].sum()
    gen_pod = generated.groupby("pod")["generated"].sum()
    val_pod = heldout.groupby("pod")["probability"].sum()
    top = cal_pod.nlargest(12).index
    pod_plot = pd.DataFrame(
        {
            "pod": top,
            "calibration": cal_pod.reindex(top).to_numpy(),
            "generated": gen_pod.reindex(top, fill_value=0).to_numpy(),
            "heldout": val_pod.reindex(top, fill_value=0).to_numpy(),
        }
    )
    pod_plot.to_csv(
        output_dir / "attribute_fig1_pod_data.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.15))
    ax = axes[0]
    x = np.arange(len(top))
    width = 0.26
    ax.bar(x - width, pod_plot["calibration"] * 100, width, color=BLUE, label="Calibration")
    ax.bar(x, pod_plot["generated"] * 100, width, color=GREEN, label="Generated")
    ax.bar(x + width, pod_plot["heldout"] * 100, width, color=ORANGE, label="Held-out")
    ax.set_xticks(x, top, rotation=55, ha="right")
    ax.set_ylabel("Share of export boxes (%)")
    ax.set_title("(a) Twelve largest calibration PODs")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=3, loc="upper right")

    ax = axes[1]
    marginal_rows = []
    for attribute, values in (
        ("Size", [20, 40]),
        ("Height", ["STD", "HIGH"]),
    ):
        column = "size_ft" if attribute == "Size" else "height_class"
        for value in values:
            marginal_rows.append(
                {
                    "attribute": f"{value} ft" if attribute == "Size" else value,
                    "calibration": calibration.loc[
                        calibration[column] == value, "probability"
                    ].sum(),
                    "generated": generated.loc[
                        generated[column] == value, "generated"
                    ].sum(),
                    "heldout": heldout.loc[
                        heldout[column] == value, "probability"
                    ].sum(),
                }
            )
    marginal = pd.DataFrame(marginal_rows)
    marginal.to_csv(
        output_dir / "attribute_fig1_marginal_data.csv",
        index=False,
        encoding="utf-8-sig",
    )
    x = np.arange(len(marginal))
    ax.bar(x - width, marginal["calibration"] * 100, width, color=BLUE)
    ax.bar(x, marginal["generated"] * 100, width, color=GREEN)
    ax.bar(x + width, marginal["heldout"] * 100, width, color=ORANGE)
    ax.set_xticks(x, marginal["attribute"])
    ax.set_ylabel("Share of export boxes (%)")
    ax.set_title("(b) Model-compatible marginals")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    fig.subplots_adjust(wspace=0.30)
    save(fig, output_dir, "attribute_fig1_distribution_fidelity")


def heterogeneity_figure(
    calls: pd.DataFrame, profiles: pd.DataFrame, validation: pd.DataFrame, output_dir: Path
) -> None:
    observed_profiles = profiles[
        ["IYC_EVOY_ID", "voyage_observed_boxes", "voyage_observed_pods"]
    ].drop_duplicates()
    observed_profiles.to_csv(
        output_dir / "attribute_fig2_yangshan_voyages.csv",
        index=False,
        encoding="utf-8-sig",
    )
    calls[
        ["call_id", "synthetic_export_boxes", "synthetic_pod_count", "period"]
    ].to_csv(
        output_dir / "attribute_fig2_pnc_calls.csv",
        index=False,
        encoding="utf-8-sig",
    )

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    ax = axes[0]
    bins = np.arange(0.5, 13.6, 1)
    ax.hist(
        observed_profiles["voyage_observed_pods"],
        bins=bins,
        density=True,
        color=BLUE,
        alpha=0.55,
        label="Yangshan observed voyages",
    )
    ax.hist(
        calls["synthetic_pod_count"],
        bins=bins,
        density=True,
        histtype="step",
        color=GREEN,
        linewidth=1.8,
        label="Generated PNC calls",
    )
    ax.set_xlabel("Distinct PODs per export voyage/call")
    ax.set_ylabel("Density")
    ax.set_title("(a) Voyage-level POD sparsity")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.legend(frameon=False)

    ax = axes[1]
    joint = validation.loc[
        (validation["scenario"] == "observed")
        & (validation["dimension"] == "joint")
    ].copy()
    x = np.arange(len(joint))
    ax.bar(
        x - 0.18,
        joint["tv_to_calibration"],
        0.36,
        color=GREEN,
        label="To calibration",
    )
    ax.bar(
        x + 0.18,
        joint["tv_to_heldout"],
        0.36,
        color=ORANGE,
        label="To held-out",
    )
    ax.set_xticks(x, joint["period"].str[-2:])
    ax.set_xlabel("Month in 2026")
    ax.set_ylabel("Joint total-variation distance")
    ax.set_title("(b) Distribution validation")
    ax.grid(axis="y")
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    save(fig, output_dir, "attribute_fig2_sparsity_validation")


def write_captions(output_dir: Path) -> None:
    text = """# Suggested figure captions

## Attribute Figure 1

Distribution fidelity of the semi-synthetic export attributes. PNC supplies
the observed export total for each call, while POD, size, and height are
generated jointly from Yangshan observations. The held-out Yangshan snapshot
is shown only for temporal validation and is not used in generation.

## Attribute Figure 2

Voyage heterogeneity and temporal validation. Panel (a) compares the number of
distinct PODs in observed Yangshan voyage profiles and generated PNC calls.
Panel (b) reports joint POD-size-height total-variation distance to the
calibration and held-out distributions. The generator uses size-matched
observed voyage profiles to avoid assigning the full port-wide POD support to
every call.
"""
    (output_dir / "attribute_figure_captions.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attribute-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/"
            "pnc_export_attribute_disaggregation"
        ),
    )
    parser.add_argument(
        "--yangshan-root",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/yangshan_observed_calibration"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "local_results/protocol_v2_pnc_yangshan/figures/"
            "pnc_export_attributes"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_style()
    groups = pd.read_csv(args.attribute_root / "export_groups_model_ready.csv")
    calls = pd.read_csv(args.attribute_root / "export_calls_model_ready.csv")
    validation = pd.read_csv(args.attribute_root / "distribution_validation.csv")
    calibration = pd.read_csv(args.yangshan_root / "observed_joint_distribution.csv")
    heldout = pd.read_csv(args.yangshan_root / "heldout_joint_distribution.csv")
    profiles = pd.read_csv(args.yangshan_root / "observed_voyage_group_profiles.csv")
    marginal_figure(groups, calibration, heldout, args.output_dir)
    heterogeneity_figure(calls, profiles, validation, args.output_dir)
    write_captions(args.output_dir)
    print(f"Wrote attribute figures to {args.output_dir}")


if __name__ == "__main__":
    main()

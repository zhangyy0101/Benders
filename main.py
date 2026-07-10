"""
Entry point for the BBC pipeline.

Runs the three-phase Branch-and-Benders-Cut + Adaptive LNS solver on a
selected instance and saves a JSON summary of the run.

Usage:
    python -u main.py                         # default: 3new6old, strict LB mode
    python -u main.py --instance baptbi_10n_4b_4p
    python -u main.py --instance barcelona_bcn36a_10n
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict
from datetime import datetime

from config import Weights
from data import (
    get_data_baptbi_10n_4b_4p,
    get_data_baptbi_15n_4b_5p,
    get_data_baptbi_25n_6b_5p,
    get_data_baptbi_5n_4b_4p,
    get_data_baptbi_8n_4b_4p,
    get_data_barcelona_bcn36a_5n,
    get_data_barcelona_bcn36a_8n,
    get_data_barcelona_bcn36a_10n,
    get_data_barcelona_bcn36a_20n,
    get_data_3new6old_fixed,
)
from solver_bbc import solve_pipeline_v2, _group_attr, _group_size, _new_groups


INSTANCES = {
    "3new6old": get_data_3new6old_fixed,
    "baptbi_5n_4b_4p": get_data_baptbi_5n_4b_4p,
    "baptbi_8n_4b_4p": get_data_baptbi_8n_4b_4p,
    "baptbi_10n_4b_4p": get_data_baptbi_10n_4b_4p,
    "baptbi_15n_4b_5p": get_data_baptbi_15n_4b_5p,
    "baptbi_25n_6b_5p": get_data_baptbi_25n_6b_5p,
    "barcelona_bcn36a_5n": get_data_barcelona_bcn36a_5n,
    "barcelona_bcn36a_8n": get_data_barcelona_bcn36a_8n,
    "barcelona_bcn36a_10n": get_data_barcelona_bcn36a_10n,
    "barcelona_bcn36a_20n": get_data_barcelona_bcn36a_20n,
}


STATUS_NAMES = {
    2: "OPTIMAL",
    3: "INFEASIBLE",
    4: "INF_OR_UNBD",
    5: "UNBOUNDED",
    9: "TIME_LIMIT",
    11: "INTERRUPTED",
    13: "SUBOPTIMAL",
}


def _status_name(status) -> str:
    if status is None:
        return "NA"
    return STATUS_NAMES.get(int(status), str(status))


def _pct(value) -> str:
    if not isinstance(value, (int, float)):
        return "NA"
    if value == float("inf"):
        return "inf"
    return f"{100.0 * float(value):.2f}%"


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value))


def _svg_escape(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _write_text(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _palette() -> list[str]:
    return [
        "#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
        "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC",
        "#6B6ECF", "#D37295", "#55A868", "#C44E52", "#8172B3",
    ]


def _build_solution_snapshot(data: dict, mp_fix: dict) -> dict:
    if not mp_fix:
        return {}
    final_n = max(data["N"]) if data.get("N") else 0
    groups = _new_groups(data)
    alloc = mp_fix.get("alloc_boxes", {})
    in_share = mp_fix.get("in_share", {})
    ship_color = {j: _palette()[idx % len(_palette())] for idx, j in enumerate(data["J_new"])}

    bay_rows = []
    for bay in data["I_list"]:
        by_ship = {}
        by_size = {}
        by_pod = {}
        by_height = {}
        by_weight = {}
        for j in data["J_new"]:
            for g in groups:
                val = float(alloc.get((bay, j, g, final_n), 0.0))
                if val > 1e-6:
                    by_ship[j] = by_ship.get(j, 0.0) + val
                    by_size[str(_group_size(data, g))] = by_size.get(str(_group_size(data, g)), 0.0) + val
                    by_pod[_group_attr(data, g, "pod")] = by_pod.get(_group_attr(data, g, "pod"), 0.0) + val
                    by_height[_group_attr(data, g, "height")] = by_height.get(_group_attr(data, g, "height"), 0.0) + val
                    by_weight[_group_attr(data, g, "weight_class")] = by_weight.get(_group_attr(data, g, "weight_class"), 0.0) + val
        dominant_ship = max(by_ship, key=by_ship.get) if by_ship else ""
        bay_rows.append({
            "block": data["I"][bay]["block"],
            "bay": bay,
            "mode_ft": int(data["I"][bay].get("fixed_size_ft", 40)),
            "dominant_ship": dominant_ship,
            "dominant_color": ship_color.get(dominant_ship, "#FFFFFF"),
            "new_boxes_final": round(sum(by_ship.values()), 4),
            "by_ship": {k: round(v, 4) for k, v in sorted(by_ship.items())},
            "by_size": by_size,
            "by_pod": {k: round(v, 4) for k, v in sorted(by_pod.items())},
            "by_height": {k: round(v, 4) for k, v in sorted(by_height.items())},
            "by_weight_class": {k: round(v, 4) for k, v in sorted(by_weight.items())},
        })

    ship_block = []
    for j in data["J_new"]:
        row = {"ship": j, "blocks": {}}
        for k in data["K"]:
            row["blocks"][k] = round(sum(
                float(in_share.get((j, k, g, n), 0.0))
                for g in groups for n in data["N"]
            ), 4)
        ship_block.append(row)

    block_timeline = []
    for k in data["K"]:
        values = []
        for n in data["N"]:
            val = mp_fix.get("in_total", {}).get((k, n))
            if val is None:
                val = sum(
                    float(in_share.get((j, k, g, n), 0.0))
                    for j in data["J_new"] for g in groups
                )
            values.append(round(float(val), 4))
        block_timeline.append({"block": k, "values": values})

    return {
        "final_interval": final_n,
        "ships": list(data["J_new"]),
        "blocks": list(data["K"]),
        "ship_colors": ship_color,
        "bay_rows": bay_rows,
        "ship_block": ship_block,
        "block_timeline": block_timeline,
    }


def _write_bay_assignment_svg(data: dict, snapshot: dict, out_dir: str) -> str:
    rows_by_block = {k: [] for k in data["K"]}
    for row in snapshot["bay_rows"]:
        rows_by_block[row["block"]].append(row)

    cell_w, cell_h = 86, 42
    left, top = 110, 42
    max_bays = max((len(v) for v in rows_by_block.values()), default=1)
    width = left + max_bays * cell_w + 30
    height = top + len(data["K"]) * cell_h + 90
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="20" y="26" font-family="Arial" font-size="18" font-weight="700">Final bay allocation</text>',
        f'<text x="260" y="26" font-family="Arial" font-size="12" fill="#555">final interval={snapshot["final_interval"]}</text>',
    ]
    for r_idx, k in enumerate(data["K"]):
        y = top + r_idx * cell_h
        parts.append(f'<text x="18" y="{y + 27}" font-family="Arial" font-size="13" font-weight="700">{_svg_escape(k)}</text>')
        for c_idx, row in enumerate(rows_by_block[k]):
            x = left + c_idx * cell_w
            fill = row["dominant_color"] if row["dominant_ship"] else "#F2F2F2"
            stroke = "#333333" if row["new_boxes_final"] > 1e-6 else "#BBBBBB"
            label = row["dominant_ship"].replace("BAPTBI_", "")[-8:] if row["dominant_ship"] else "-"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 4}" height="{cell_h - 5}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
            parts.append(f'<text x="{x + 4}" y="{y + 14}" font-family="Arial" font-size="9" fill="#111">{_svg_escape(row["bay"].split("_")[-1])}</text>')
            parts.append(f'<text x="{x + 4}" y="{y + 27}" font-family="Arial" font-size="9" fill="#111">{_svg_escape(label)}</text>')
            parts.append(f'<text x="{x + cell_w - 28}" y="{y + 27}" font-family="Arial" font-size="9" fill="#111">{row["new_boxes_final"]:.0f}</text>')
    legend_y = height - 40
    parts.append(f'<text x="20" y="{legend_y}" font-family="Arial" font-size="12" fill="#555">Cell color = dominant new ship in bay; number = final allocated boxes.</text>')
    parts.append("</svg>")
    return _write_text(os.path.join(out_dir, "bay_assignment_final.svg"), "\n".join(parts))


def _write_ship_block_heatmap_svg(data: dict, snapshot: dict, out_dir: str) -> str:
    matrix = snapshot["ship_block"]
    vals = [v for row in matrix for v in row["blocks"].values()]
    max_val = max(vals) if vals else 1.0
    cell_w, cell_h = 72, 26
    left, top = 170, 54
    width = left + len(data["K"]) * cell_w + 30
    height = top + len(matrix) * cell_h + 60
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="20" y="26" font-family="Arial" font-size="18" font-weight="700">Ship-block inbound heatmap</text>',
    ]
    for c_idx, k in enumerate(data["K"]):
        x = left + c_idx * cell_w
        parts.append(f'<text x="{x + 4}" y="46" font-family="Arial" font-size="10" transform="rotate(-30 {x + 4},46)">{_svg_escape(k)}</text>')
    for r_idx, row in enumerate(matrix):
        y = top + r_idx * cell_h
        ship_label = row["ship"].replace("BAPTBI_", "")[-18:]
        parts.append(f'<text x="18" y="{y + 17}" font-family="Arial" font-size="10">{_svg_escape(ship_label)}</text>')
        for c_idx, k in enumerate(data["K"]):
            x = left + c_idx * cell_w
            val = row["blocks"][k]
            ratio = 0.0 if max_val <= 0 else min(1.0, val / max_val)
            blue = int(245 - 135 * ratio)
            fill = f"rgb({blue},{blue + 5},255)"
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 3}" height="{cell_h - 3}" fill="{fill}" stroke="#dddddd"/>')
            if val > 1e-6:
                parts.append(f'<text x="{x + 6}" y="{y + 16}" font-family="Arial" font-size="9" fill="#111">{val:.0f}</text>')
    parts.append("</svg>")
    return _write_text(os.path.join(out_dir, "ship_block_heatmap.svg"), "\n".join(parts))


def _write_block_timeline_svg(data: dict, snapshot: dict, out_dir: str) -> str:
    width, height = 980, 420
    left, right, top, bottom = 60, 170, 45, 60
    plot_w = width - left - right
    plot_h = height - top - bottom
    max_val = max((v for row in snapshot["block_timeline"] for v in row["values"]), default=1.0)
    max_val = max(max_val, 1.0)
    n_count = max(1, len(data["N"]) - 1)
    colors = _palette()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<text x="20" y="26" font-family="Arial" font-size="18" font-weight="700">Block total inbound timeline</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#888"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#888"/>',
    ]
    for idx, row in enumerate(snapshot["block_timeline"]):
        pts = []
        for p_idx, val in enumerate(row["values"]):
            x = left + plot_w * (p_idx / n_count)
            y = top + plot_h * (1.0 - float(val) / max_val)
            pts.append(f"{x:.1f},{y:.1f}")
        color = colors[idx % len(colors)]
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
        ly = top + 16 + idx * 18
        parts.append(f'<rect x="{left + plot_w + 24}" y="{ly - 10}" width="12" height="12" fill="{color}"/>')
        parts.append(f'<text x="{left + plot_w + 42}" y="{ly}" font-family="Arial" font-size="11">{_svg_escape(row["block"])}</text>')
    parts.append(f'<text x="20" y="{height - 18}" font-family="Arial" font-size="12" fill="#555">Y-axis max={max_val:.1f}; X-axis intervals={len(data["N"])}</text>')
    parts.append("</svg>")
    return _write_text(os.path.join(out_dir, "block_inbound_timeline.svg"), "\n".join(parts))


def _write_visual_outputs(data: dict, pipe: dict, out_dir: str) -> list[str]:
    mp_fix = (pipe.get("final_mp_fix") or pipe.get("best_mp_fix")) if pipe else None
    if not mp_fix:
        return []
    snapshot = _build_solution_snapshot(data, mp_fix)
    if not snapshot:
        return []
    snapshot_path = os.path.join(out_dir, "solution_snapshot.json")
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)
    paths = [
        snapshot_path,
        _write_bay_assignment_svg(data, snapshot, out_dir),
        _write_ship_block_heatmap_svg(data, snapshot, out_dir),
        _write_block_timeline_svg(data, snapshot, out_dir),
    ]
    return [os.path.basename(p) for p in paths]


def _summary_dict(pipe: dict) -> dict:
    """JSON-serializable summary of a pipeline result."""
    out: dict = {"best_ub": pipe.get("best_ub")}

    p1 = pipe.get("phase1") or {}
    p2 = pipe.get("lns") or {}
    p3 = pipe.get("phase3") or {}
    pattr = pipe.get("attribute_polish") or {}

    out["phase1_bbc"] = {
        "status": p1.get("status"),
        "status_name": _status_name(p1.get("status")),
        "stop_reason": p1.get("stop_reason"),
        "lb": p1.get("lb"),
        "ub": p1.get("best_ub"),
        "mp_obj": p1.get("mp_obj"),
        "gap": p1.get("gap"),
        "balance_lb_mode": p1.get("balance_lb_mode"),
        "ub_balance_mode": p1.get("ub_balance_mode"),
        "user_cuts_added": p1.get("user_cuts_added"),
        "node_benders_cuts_added": p1.get("node_benders_cuts_added"),
        "feas_cuts_added": p1.get("feas_cuts_added"),
        "node_feas_cuts_added": p1.get("node_feas_cuts_added"),
        "sp_solves": p1.get("sp_solves"),
        "node_sp_solves": p1.get("node_sp_solves"),
        "sp_infeas": p1.get("sp_infeas"),
        "node_sp_infeas": p1.get("node_sp_infeas"),
        "node_separations": p1.get("node_separations"),
        "mipnode_calls": p1.get("mipnode_calls"),
        "mipnode_nonoptimal": p1.get("mipnode_nonoptimal"),
        "mipnode_cache_hits": p1.get("mipnode_cache_hits"),
        "mipnode_no_cut": p1.get("mipnode_no_cut"),
        "mipnode_budget_skips": p1.get("mipnode_budget_skips"),
        "wall_time_s": p1.get("time_total_s"),
    } if p1 else None

    out["phase2_alns"] = {
        "ub": p2.get("best_ub"),
        "iters": p2.get("iters_attempted", (len(p2.get("history", [])) - 1) if p2.get("history") else 0),
        "sa_accepts": p2.get("sa_accepts"),
        "wall_time_s": p2.get("time_total_s"),
        "stop_reason": p2.get("stop_reason"),
        "restarts": p2.get("restarts"),
        "seed": p2.get("seed"),
        "best_no_improve_iters": p2.get("best_no_improve_iters"),
        "op_weights_final": p2.get("op_weights_final"),
    } if p2 else None

    out["phase3_bbc_restart"] = {
        "status": p3.get("status"),
        "status_name": _status_name(p3.get("status")),
        "stop_reason": p3.get("stop_reason"),
        "lb": p3.get("lb"),
        "ub": p3.get("best_ub"),
        "mp_obj": p3.get("mp_obj"),
        "gap": p3.get("gap"),
        "balance_lb_mode": p3.get("balance_lb_mode"),
        "ub_balance_mode": p3.get("ub_balance_mode"),
        "user_cuts_added": p3.get("user_cuts_added"),
        "node_benders_cuts_added": p3.get("node_benders_cuts_added"),
        "feas_cuts_added": p3.get("feas_cuts_added"),
        "node_feas_cuts_added": p3.get("node_feas_cuts_added"),
        "sp_solves": p3.get("sp_solves"),
        "node_sp_solves": p3.get("node_sp_solves"),
        "sp_infeas": p3.get("sp_infeas"),
        "node_sp_infeas": p3.get("node_sp_infeas"),
        "node_separations": p3.get("node_separations"),
        "mipnode_calls": p3.get("mipnode_calls"),
        "mipnode_nonoptimal": p3.get("mipnode_nonoptimal"),
        "mipnode_cache_hits": p3.get("mipnode_cache_hits"),
        "mipnode_no_cut": p3.get("mipnode_no_cut"),
        "mipnode_budget_skips": p3.get("mipnode_budget_skips"),
        "wall_time_s": p3.get("time_total_s"),
    } if p3 else None

    out["attribute_polish"] = {
        "status": pattr.get("status"),
        "status_name": _status_name(pattr.get("status")),
        "accepted": pattr.get("accepted"),
        "core_tolerance": pattr.get("core_tolerance"),
        "core_cap": pattr.get("core_cap"),
        "start_core_cost": pattr.get("start_core_cost"),
        "candidate_core_cost": pattr.get("candidate_core_cost"),
        "core_degradation_vs_start": pattr.get("core_degradation_vs_start"),
        "start_attribute_score": pattr.get("start_attribute_score"),
        "candidate_attribute_score": pattr.get("candidate_attribute_score"),
        "start_components": pattr.get("start_components"),
        "candidate_components": pattr.get("candidate_components"),
        "candidate_feasible": pattr.get("candidate_feasible"),
        "model_obj": pattr.get("model_obj"),
        "model_bound": pattr.get("model_bound"),
        "model_gap": pattr.get("model_gap"),
        "wall_time_s": pattr.get("time_total_s"),
        "sol_count": pattr.get("sol_count"),
        "node_count": pattr.get("node_count"),
    } if pattr else None

    # Reported gap = best UB across phases vs best valid lower bound seen.
    # L1 balance is represented exactly in the lifted master, so the BBC and
    # Phase 3 bounds are for the same linearized objective.
    lb_candidates = [
        float(v) for v in (p1.get("lb"), p3.get("lb"))
        if isinstance(v, (int, float))
    ]
    final_lb = max(lb_candidates) if lb_candidates else 0.0
    final_ub = pipe.get("best_ub") or 0.0
    out["reported_lb"] = final_lb
    out["reported_ub"] = final_ub
    if final_ub > 0:
        out["reported_gap"] = (final_ub - final_lb) / final_ub
    out["final_solution_source"] = (
        "attribute_polish"
        if pattr and pattr.get("accepted")
        else "core_best"
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="BBC v2 pipeline runner")
    parser.add_argument("--instance", choices=INSTANCES.keys(), default="3new6old",
                        help="instance to solve (default: 3new6old)")
    parser.add_argument("--data-only", action="store_true",
                        help="build the selected instance and print basic data statistics without solving")
    parser.add_argument("--no-node-cuts", action="store_true",
                        help="disable fractional-node user cuts")
    parser.add_argument("--node-cut-limit", type=int, default=250,
                        help="max fractional-node Benders/Farkas user cuts per BBC phase")
    parser.add_argument("--no-alns", action="store_true",
                        help="skip Phase 2 ALNS (BBC only)")
    parser.add_argument("--lns-stall-iters", type=int, default=8,
                        help="stop ALNS after this many iterations without best UB improvement (default: 8)")
    parser.add_argument("--lns-min-iters", type=int, default=1,
                        help="minimum ALNS iterations before adaptive stop can trigger (default: 1)")
    parser.add_argument("--lns-min-time", type=float, default=15.0,
                        help="minimum ALNS seconds before adaptive stop can trigger (default: 15)")
    parser.add_argument("--no-bbc-reported-gap-stop", action="store_true",
                        help="disable BBC early stop based on reported UB/LB gap")
    parser.add_argument("--phase3-lb-stall-time", type=float, default=6.0,
                        help="stop Phase 3 BBC if LB does not improve for this many seconds (default: 6)")
    parser.add_argument("--no-phase3-lb-stall-stop", action="store_true",
                        help="disable Phase 3 LB-stall early stop")
    parser.add_argument("--phase1-time", type=float, default=20.0,
                        help="maximum seconds for Phase 1 BBC (default: 20)")
    parser.add_argument("--lns-time", type=float, default=45.0,
                        help="maximum seconds for Phase 2 ALNS (default: 45)")
    parser.add_argument("--lns-iters", type=int, default=25,
                        help="maximum ALNS repair iterations (default: 25)")
    parser.add_argument("--phase3-time", type=float, default=20.0,
                        help="maximum seconds for Phase 3 BBC proof/LB phase (default: 20)")
    parser.add_argument("--phase3-lb-stall-gap-guard", type=float, default=None,
                        help="allow Phase 3 LB-stall stop only when reported gap is at or below this value; "
                             "default follows the target gap")
    parser.add_argument("--lns-sub-mip-time", type=float, default=16.0,
                        help="seconds for each ALNS repair sub-MIP (default: 16)")
    parser.add_argument("--lns-restarts", type=int, default=1,
                        help="number of independent ALNS restarts with different seeds (default: 1)")
    parser.add_argument("--lns-seed-base", type=int, default=42,
                        help="base random seed for ALNS restarts (default: 42)")
    parser.add_argument("--attribute-polish-time", type=float, default=20.0,
                        help="seconds for post-solve pod/weight/height layout polish (default: 20)")
    parser.add_argument("--attribute-polish-core-tolerance", type=float, default=0.01,
                        help="allowed core objective degradation during attribute polish (default: 0.01)")
    parser.add_argument("--attribute-polish-gap", type=float, default=0.03,
                        help="relative MIP gap target for attribute polish (default: 0.03)")
    parser.add_argument("--no-attribute-polish", action="store_true",
                        help="disable post-solve attribute layout polish")
    parser.add_argument("--output-root", default="outputs",
                        help="root directory for run outputs (default: outputs)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-iteration ALNS log lines")
    args = parser.parse_args()

    data = INSTANCES[args.instance]()
    if args.data_only:
        grouped_arrivals = data.get("Arrivals_group_interval")
        total_arrivals = sum(float(v) for v in (grouped_arrivals or data["Arrivals_interval"]).values())
        total_fixed_in = sum(float(v) for v in data["Fixed_In_Flow"].values())
        total_old_out = sum(float(v) for v in data["Block_Outbound_Vol"].values())
        total_capacity = sum(float(info["cap"]) for info in data["I"].values())
        groups = _new_groups(data)
        print(f"[data] instance        = {args.instance}")
        print(f"[data] blocks/bays     = {len(data['K'])}/{len(data['I_list'])}")
        print(f"[data] ships new/old   = {len(data['J_new'])}/{len(data['J_old'])}")
        print(f"[data] intervals       = {len(data['N'])}")
        print(f"[data] new groups      = {len(groups)}")
        print(f"[data] total arrivals  = {total_arrivals:.2f}")
        print(f"[data] fixed old in    = {total_fixed_in:.2f}")
        print(f"[data] old outbound    = {total_old_out:.2f}")
        print(f"[data] yard capacity   = {total_capacity:.2f}")
        meta = data.get("benchmark_metadata")
        if meta:
            print(f"[data] benchmark       = {meta.get('source', '')} / {meta.get('name', '')}")
            print(f"[data] original file   = {bool(meta.get('is_original_file', False))}")
        return 0
    weights = Weights()

    bbc_phase1_time_s = args.phase1_time
    lns_time_s = args.lns_time
    bbc_phase3_time_s = args.phase3_time
    lns_iters = args.lns_iters
    bbc_phase3_target_gap = None if args.no_bbc_reported_gap_stop else 0.03
    phase3_lb_stall_gap_guard = (
        args.phase3_lb_stall_gap_guard
        if args.phase3_lb_stall_gap_guard is not None
        else bbc_phase3_target_gap
    )

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.abspath(os.path.join(args.output_root, f"benders_run_{run_id}_{_safe_name(args.instance)}"))
    os.makedirs(out_dir, exist_ok=True)

    print(f"[main] instance        = {args.instance}")
    print("[main] mode            = strict")
    lns_budget_msg = "adaptive" if lns_time_s is None else f"max={lns_time_s:g}s"
    phase3_budget_msg = "adaptive" if bbc_phase3_time_s is None else f"max={bbc_phase3_time_s:g}s"
    print(f"[main] phase budgets   = BBC1 max={bbc_phase1_time_s:g}s / "
          f"ALNS {lns_budget_msg} x{max(1, args.lns_restarts)} / BBC2 {phase3_budget_msg}")
    bbc2_gap_msg = "off" if args.no_bbc_reported_gap_stop else "3%"
    bbc2_stall_msg = "off" if args.no_phase3_lb_stall_stop else f"{args.phase3_lb_stall_time:g}s"
    attribute_polish_time = None if args.no_attribute_polish else args.attribute_polish_time
    attribute_polish_msg = (
        "off"
        if attribute_polish_time is None or attribute_polish_time <= 0
        else f"{attribute_polish_time:g}s tol={100.0 * args.attribute_polish_core_tolerance:.1f}%"
    )
    bbc2_guard_msg = "off" if phase3_lb_stall_gap_guard is None else _pct(phase3_lb_stall_gap_guard)
    print("[main] adaptive stops  = BBC1 min=10s feas-stall=5s; "
          f"ALNS min={args.lns_min_time:g}s no-improve={args.lns_stall_iters}; "
          f"BBC2 gap={bbc2_gap_msg} lb-stall={bbc2_stall_msg} "
          f"stall-guard={bbc2_guard_msg} balance=L1; "
          f"attr-polish={attribute_polish_msg}")
    print(f"[main] output dir      = {out_dir}")

    pipe = solve_pipeline_v2(
        data, weights,
        bbc_phase1_time_s=bbc_phase1_time_s,
        lns_time_s=lns_time_s,
        lns_iters=lns_iters,
        lns_sub_mip_time=args.lns_sub_mip_time,
        bbc_phase3_time_s=bbc_phase3_time_s,
        use_alns=not args.no_alns,
        use_node_cuts=not args.no_node_cuts,
        node_cut_limit=args.node_cut_limit,
        adaptive_lns_time=True,
        lns_early_stop_no_improve_iters=args.lns_stall_iters,
        lns_early_stop_min_iters=args.lns_min_iters,
        lns_early_stop_min_time_s=args.lns_min_time,
        lns_restarts=args.lns_restarts,
        lns_seed_base=args.lns_seed_base,
        attribute_polish_time_s=attribute_polish_time,
        attribute_polish_core_tolerance=args.attribute_polish_core_tolerance,
        attribute_polish_mip_gap=args.attribute_polish_gap,
        bbc_phase1_min_time_s=10.0,
        bbc_phase1_feas_cut_stall_time_s=5.0,
        bbc_phase3_reported_gap_stop=bbc_phase3_target_gap,
        bbc_phase3_lb_stall_time_s=None if args.no_phase3_lb_stall_stop else args.phase3_lb_stall_time,
        bbc_phase3_lb_stall_min_time_s=0.0,
        bbc_phase3_lb_stall_gap_guard=phase3_lb_stall_gap_guard,
        verbose=not args.quiet,
    )

    summary = _summary_dict(pipe)
    summary["instance"] = args.instance
    summary["mode"] = "strict"
    summary["weights"] = asdict(weights)
    summary["visualizations"] = _write_visual_outputs(data, pipe, out_dir)

    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    # Pretty terminal report
    print()
    print("=" * 70)
    print("Final result")
    print(f"  UB={pipe['best_ub']:.2f}  LB={summary['reported_lb']:.2f}  "
          f"gap={_pct(summary.get('reported_gap'))}")
    p3_balance_mode = (
        (summary.get("phase3_bbc_restart") or {}).get("balance_lb_mode")
        or (summary.get("phase1_bbc") or {}).get("balance_lb_mode")
        or "L1"
    )
    print(f"  Core LB/UB both use exact {p3_balance_mode} balance evaluation")
    print(f"  Final plan source: {summary.get('final_solution_source')}")
    if summary["phase1_bbc"]:
        p = summary["phase1_bbc"]
        print()
        stop_note = f", stop={p['stop_reason']}" if p.get("stop_reason") else ""
        print(f"Phase 1 BBC: status={p['status_name']}{stop_note}  time={p['wall_time_s']:.1f}s  gap={_pct(p['gap'])}")
        print(f"  LB={p['lb']:.2f}  UB={p['ub']:.2f}")
        print(f"  SP checks: incumbent={p['sp_solves']}  node={p['node_sp_solves']}  "
              f"node_separations={p['node_separations']}  user={p['user_cuts_added']}")
        print(f"  SP infeas: incumbent={p['sp_infeas']}  node={p['node_sp_infeas']}  "
              f"feas_cuts={p['feas_cuts_added']}  node_feas_cuts={p['node_feas_cuts_added']}")
        print(f"  MIPNODE: calls={p['mipnode_calls']}  nonoptimal={p['mipnode_nonoptimal']}  "
              f"cache_hits={p['mipnode_cache_hits']}  no_cut={p['mipnode_no_cut']}  "
              f"budget_skips={p['mipnode_budget_skips']}")
    if summary["phase2_alns"]:
        p = summary["phase2_alns"]
        print()
        print(f"Phase 2 ALNS: stop={p['stop_reason']}  time={p['wall_time_s']:.1f}s  iters={p['iters']}")
        print(f"  UB={p['ub']:.2f}  SA accepts={p['sa_accepts']}")
    if summary["phase3_bbc_restart"]:
        p = summary["phase3_bbc_restart"]
        print()
        stop_note = f", stop={p['stop_reason']}" if p.get("stop_reason") else ""
        print(f"Phase 3 BBC proof/LB: status={p['status_name']}{stop_note}  time={p['wall_time_s']:.1f}s  gap={_pct(p['gap'])}")
        print(f"  LB={p['lb']:.2f}  UB={p['ub']:.2f}")
        print(f"  SP checks: incumbent={p.get('sp_solves', 0)}  node={p['node_sp_solves']}  "
              f"node_separations={p['node_separations']}  user={p['user_cuts_added']}")
        print(f"  SP infeas: incumbent={p['sp_infeas']}  node={p['node_sp_infeas']}  "
              f"feas_cuts={p['feas_cuts_added']}  node_feas_cuts={p['node_feas_cuts_added']}")
        print(f"  MIPNODE: calls={p['mipnode_calls']}  nonoptimal={p['mipnode_nonoptimal']}  "
              f"cache_hits={p['mipnode_cache_hits']}  no_cut={p['mipnode_no_cut']}  "
              f"budget_skips={p['mipnode_budget_skips']}")
    if summary.get("attribute_polish"):
        p = summary["attribute_polish"]
        print()
        accepted = "accepted" if p.get("accepted") else "not accepted"
        print(f"Attribute polish: status={p['status_name']}  time={p['wall_time_s']:.1f}s  {accepted}")
        if isinstance(p.get("candidate_core_cost"), (int, float)):
            print(f"  core cost={p['candidate_core_cost']:.2f}  "
                  f"degradation={_pct(p.get('core_degradation_vs_start'))}  "
                  f"cap={p.get('core_cap'):.2f}")
        if isinstance(p.get("candidate_attribute_score"), (int, float)):
            print(f"  attribute score: {p.get('start_attribute_score'):.2f} -> "
                  f"{p.get('candidate_attribute_score'):.2f}")
        comps = p.get("candidate_components") or p.get("start_components")
        if comps:
            print(f"  components: pod={comps.get('pod_spread')}  "
                  f"weight={comps.get('weight_spread')}  height={comps.get('height_mix')}")
    print()
    print(f"Summary saved to: {summary_path}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Branch-and-Benders-Cut + Adaptive LNS for the container-yard problem.

Architecture (per-ship SP decomposition with lifted master):
  1. Master holds in_share[j,k,s,n] (per-size, per-ship, per-block inbound)
     so balance, conflict, and distance are represented at block-flow level.
  2. Master objective contains open-bay cost, exact L1 balance cost, conflict cost,
     and the exact linear distance cost on in_share[j,k,s,n].
  3. Per-ship SP_j checks bay-level feasibility under alloc/x/in_share and
     supplies Farkas feasibility cuts when needed.
  4. The B&B callback adds lazy feasibility cuts at MIPSOL and valid user cuts
     at fractional MIPNODE points.
  5. Adaptive LNS polishes the incumbent with repair sub-MIPs that use the
     same lifted master and lazy feasibility-cut logic.
  6. Pipeline = Phase 1 BBC -> Phase 2 ALNS -> Phase 3 proof/LB
     -> optional attribute polish.

All cuts are strict. There is no cut weakening mode.
"""

from __future__ import annotations

import math
import random
import time
from collections import defaultdict
from itertools import combinations
from typing import Optional

import gurobipy as gp
from gurobipy import GRB

from config import AttributePolishWeights, Weights


# =====================================================================
# Bay-mode derivation (data-driven; no decision variables for size mode).
# =====================================================================
def _derive_bay_size_map(data: dict) -> dict:
    """
    Each bay has a fixed size mode (20ft or 40ft) determined by the
    instance data. This map is used by the constructive warm start.
    """
    I = data.get("I", {})
    I_list = list(data.get("I_list", []) or [])
    S = list(data.get("S", []) or [])
    N = list(data.get("N", []) or [])
    fixed_bay_mode = data.get("Fixed_Bay_Mode", {}) or {}
    fixed_mode_force = data.get("Fixed_Mode_Force", {}) or {}
    valid_sizes = {int(s) for s in S}

    bay_size = {}
    for i in I_list:
        mode = fixed_bay_mode.get(i)
        if mode is None and isinstance(I.get(i), dict):
            mode = I[i].get("fixed_size_ft")
        if mode is None:
            mode = next(
                (fixed_mode_force.get((i, n)) for n in N
                 if fixed_mode_force.get((i, n)) is not None),
                40,
            )
        try:
            fixed_size = int(mode)
        except Exception:
            fixed_size = 40
        if fixed_size not in valid_sizes and valid_sizes:
            fixed_size = 40 if 40 in valid_sizes else sorted(valid_sizes)[0]
        bay_size[i] = fixed_size
    return bay_size


def _compute_old_occupancy(data: dict) -> dict:
    """
    Return old-ship bay occupancy after each interval in box units.

    Old inbound is fixed at bay level. Old outbound is block-level, so it is
    released from the matching old ship's inventory inside that block in a
    deterministic bay order. Capacity is always measured in boxes.
    """
    I = data.get("I", {}) or {}
    I_list = list(data.get("I_list", []) or [])
    Bays_in_Block = data.get("Bays_in_Block", {}) or {}
    J_old = list(data.get("J_old", []) or [])
    S = list(data.get("S", []) or [])
    N = list(data.get("N", []) or [])
    initial_inventory_data = data.get("initial_inventory_data", {}) or {}
    fixed_in_flow = data.get("Fixed_In_Flow", {}) or {}
    block_outbound_req = data.get("Block_Outbound_Req", {}) or {}

    old_occ = {(i, n): 0.0 for i in I_list for n in N}
    inv = {
        (i, j, s): float(initial_inventory_data.get((i, j, s), 0.0))
        for i in I_list for j in J_old for s in S
    }

    for n in sorted(N):
        for i in I_list:
            for j in J_old:
                for s in S:
                    inv[(i, j, s)] += float(fixed_in_flow.get((j, s, i, n), 0.0))

        for k, bays in Bays_in_Block.items():
            for j in J_old:
                out_left = float(block_outbound_req.get((k, j, n), 0.0))
                if out_left <= 1e-9:
                    continue
                for i in sorted(bays):
                    for s in S:
                        key = (i, j, s)
                        take = min(inv.get(key, 0.0), out_left)
                        if take <= 1e-9:
                            continue
                        inv[key] -= take
                        out_left -= take
                        if out_left <= 1e-9:
                            break
                    if out_left <= 1e-9:
                        break

        for i in I_list:
            old_occ[(i, n)] = max(0.0, sum(inv[(i, j, s)] for j in J_old for s in S))
            if I and old_occ[(i, n)] > float(I[i].get("cap", 0.0)) + 1e-6:
                # Keep downstream capacity robust if a legacy dataset still
                # overfills a bay; data generators are adjusted separately.
                old_occ[(i, n)] = float(I[i].get("cap", 0.0))
    return old_occ


def _new_groups(data: dict) -> list:
    """Return new-box demand groups; legacy data falls back to size groups."""
    groups = list(data.get("G") or [])
    return groups if groups else list(data.get("S", []) or [])


def _group_attrs(data: dict, group) -> dict:
    attrs = data.get("GroupAttrs", {}) or {}
    out = dict(attrs.get(group, {}) or {})
    if "size" not in out:
        out["size"] = int(group)
    out.setdefault("pod", "ALL")
    out.setdefault("height", "ALL")
    out.setdefault("weight_class", "ALL")
    return out


def _group_size(data: dict, group) -> int:
    group_size = data.get("GroupSize", {}) or {}
    if group in group_size:
        return int(group_size[group])
    return int(_group_attrs(data, group).get("size", group))


def _group_attr(data: dict, group, attr: str, default: str = "ALL") -> str:
    return str(_group_attrs(data, group).get(attr, default) or default)


def _arrival(data: dict, ship: str, group, n) -> float:
    grouped = data.get("Arrivals_group_interval")
    if grouped is not None:
        return float(grouped.get((ship, group, n), 0.0))
    return float(data["Arrivals_interval"].get((ship, group, n), 0.0))


def _arrival_total(data: dict) -> float:
    return max(
        1.0,
        sum(
            _arrival(data, j, g, n)
            for j in data.get("J_new", [])
            for g in _new_groups(data)
            for n in data.get("N", [])
        ),
    )


def _fixed_in_block(data: dict) -> dict:
    K = data["K"]
    N = data["N"]
    S = data["S"]
    J_old = data["J_old"]
    Bays_in_Block = data["Bays_in_Block"]
    Fixed_In_Flow = data["Fixed_In_Flow"]
    fixed_in_block = {(k, n): 0.0 for k in K for n in N}
    for k in K:
        bays = Bays_in_Block[k]
        for n in N:
            fixed_in_block[(k, n)] = sum(
                float(Fixed_In_Flow[(j, s, i, n)])
                for i in bays for j in J_old for s in S
            )
    return fixed_in_block


def _outbound_pressure(data: dict) -> dict:
    """Smoothed outbound workload pressure used by the conflict objective."""
    K = data["K"]
    N = list(data["N"])
    raw = data["Block_Outbound_Vol"]
    pressure = {}
    for pos, n in enumerate(N):
        prev_n = N[pos - 1] if pos > 0 else None
        next_n = N[pos + 1] if pos + 1 < len(N) else None
        for k in K:
            val = float(raw.get((k, n), 0.0))
            if prev_n is not None:
                val += 0.5 * float(raw.get((k, prev_n), 0.0))
            if next_n is not None:
                val += 0.5 * float(raw.get((k, next_n), 0.0))
            pressure[(k, n)] = val
    return pressure


def _objective_scales(data: dict) -> dict:
    K = data["K"]
    I_list = data["I_list"]
    J_new = data["J_new"]
    N = data["N"]
    Intervals = data["Intervals"]
    total_boxes = _arrival_total(data)
    dist_scale = max(1.0, max((float(v) for v in data.get("Dist", {}).values()), default=1.0))
    pressure = _outbound_pressure(data)
    pressure_scale = max(1.0, max((float(v) for v in pressure.values()), default=1.0))
    total_dur = max(1.0, sum(float(Intervals[n]["dur"]) for n in N))
    max_interval_in = max(
        1.0,
        max(
            (
                sum(_arrival(data, j, g, n) for j in J_new for g in _new_groups(data))
                for n in N
            ),
            default=1.0,
        ),
    )
    groups = _new_groups(data)
    pods = {g: _group_attr(data, g, "pod") for g in groups}
    weights = {g: _group_attr(data, g, "weight_class") for g in groups}
    heights = {g: _group_attr(data, g, "height") for g in groups}
    pod_values = {v for v in pods.values() if v != "ALL"}
    weight_values = {v for v in weights.values() if v != "ALL"}
    height_values = {v for v in heights.values() if v != "ALL"}
    return {
        "open": max(1.0, len(I_list) * len(J_new) * total_dur),
        "distance": max(1.0, dist_scale * total_boxes),
        "conflict": max(1.0, pressure_scale * total_boxes),
        "balance": max(1.0, len(N) * len(K) * max_interval_in),
        "pod_spread": max(1.0, len(J_new) * len(K) * max(1, len(pod_values))),
        "weight_spread": max(1.0, len(J_new) * len(K) * max(1, len(weight_values))),
        "height_mix": max(1.0, len(I_list) * len(N) * max(1, len(height_values) - 1)),
    }


def _attribute_values(data: dict, attr: str) -> list[str]:
    values = sorted({
        _group_attr(data, g, attr)
        for g in _new_groups(data)
        if _group_attr(data, g, attr) != "ALL"
    })
    return values


def _master_raw_components_from_fix(data: dict, mp_fix: dict, in_total_v: dict | None = None) -> dict:
    K = data["K"]
    I_list = data["I_list"]
    J_new = data["J_new"]
    N = data["N"]
    G = _new_groups(data)
    Intervals = data["Intervals"]
    fixed_in_block = _fixed_in_block(data)
    pressure = _outbound_pressure(data)
    obj_x = sum(
        float(mp_fix["x"].get((i, j, n), 0.0)) * float(Intervals[n]["dur"])
        for i in I_list for j in J_new for n in N
    )
    if in_total_v is None:
        in_total_v = {}
        for k in K:
            for n in N:
                new_in = sum(
                    float(mp_fix.get("in_share", {}).get((j, k, g, n), 0.0))
                    for j in J_new for g in G
                )
                in_total_v[(k, n)] = new_in + fixed_in_block[(k, n)]
    real_l1 = 0.0
    for n in N:
        avg_v = sum(in_total_v[(k, n)] for k in K) / float(len(K))
        for k in K:
            diff = in_total_v[(k, n)] - avg_v
            real_l1 += abs(diff)
    obj_conflict = 0.0
    for k in K:
        for n in N:
            new_in = sum(
                float(mp_fix.get("in_share", {}).get((j, k, g, n), 0.0))
                for j in J_new for g in G
            )
            obj_conflict += float(pressure[(k, n)]) * new_in

    final_n = max(N) if N else 0
    pod_spread = 0.0
    pod_values = _attribute_values(data, "pod")
    if pod_values:
        for j in J_new:
            for pod in pod_values:
                for k in K:
                    boxes = sum(
                        float(mp_fix.get("alloc_boxes", {}).get((i, j, g, final_n), 0.0))
                        for i in data["Bays_in_Block"][k]
                        for g in G
                        if _group_attr(data, g, "pod") == pod
                    )
                    if boxes > 1e-6:
                        pod_spread += 1.0

    weight_spread = 0.0
    weight_values = _attribute_values(data, "weight_class")
    if weight_values:
        for j in J_new:
            for weight_class in weight_values:
                for k in K:
                    boxes = sum(
                        float(mp_fix.get("alloc_boxes", {}).get((i, j, g, final_n), 0.0))
                        for i in data["Bays_in_Block"][k]
                        for g in G
                        if _group_attr(data, g, "weight_class") == weight_class
                    )
                    if boxes > 1e-6:
                        weight_spread += 1.0

    height_mix = 0.0
    height_values = _attribute_values(data, "height")
    if height_values:
        for i in I_list:
            for n in N:
                used = set()
                for j in J_new:
                    for g in G:
                        if float(mp_fix.get("alloc_boxes", {}).get((i, j, g, n), 0.0)) > 1e-6:
                            used.add(_group_attr(data, g, "height"))
                height_mix += max(0, len(used) - 1)

    return {
        "obj_x": obj_x,
        "real_l1": real_l1,
        "obj_conflict": obj_conflict,
        "pod_spread": pod_spread,
        "weight_spread": weight_spread,
        "height_mix": height_mix,
        "in_total": in_total_v,
    }


def _objective_scale_factor(weights: Weights) -> float:
    try:
        scale = float(getattr(weights, "objective_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    return scale if scale > 0.0 else 1.0


def _weighted_master_cost(data: dict, weights: Weights, raw: dict) -> float:
    scales = _objective_scales(data)
    obj = (
        weights.master.x * raw["obj_x"] / scales["open"]
        + weights.sub.balance * raw["real_l1"] / scales["balance"]
        + weights.sub.conflict * raw["obj_conflict"] / scales["conflict"]
    )
    return _objective_scale_factor(weights) * obj


def _attribute_polish_weights(weights: Weights) -> AttributePolishWeights:
    attr = getattr(weights, "attribute", None)
    if attr is None:
        return AttributePolishWeights()
    return attr


def _attribute_score(data: dict, weights: Weights, raw: dict) -> float:
    scales = _objective_scales(data)
    attr = _attribute_polish_weights(weights)
    score = (
        float(getattr(attr, "pod_spread", 0.0)) * raw.get("pod_spread", 0.0) / scales["pod_spread"]
        + float(getattr(attr, "weight_spread", 0.0)) * raw.get("weight_spread", 0.0) / scales["weight_spread"]
        + float(getattr(attr, "height_mix", 0.0)) * raw.get("height_mix", 0.0) / scales["height_mix"]
    )
    return _objective_scale_factor(weights) * score


# =====================================================================
# Warm-start helpers (self-contained for the BBC v2 pipeline).
# =====================================================================
def _construct_avoid_outbound_initial_mp_fix(
    data: dict,
    weights: Weights,
    eps: float = 1e-9,
) -> dict | None:
    """
    Constructive primal start: prefer blocks with no outbound work, then
    lower outbound volume, then shorter ship-block distance. Capacity is
    assigned cumulatively so alloc_boxes remains nondecreasing.
    """
    K = data["K"]
    I = data["I"]
    I_list = data["I_list"]
    J_new = data["J_new"]
    G = _new_groups(data)
    N = data["N"]
    Alpha = float(data["Alpha"])
    Bays_in_Block = data["Bays_in_Block"]
    Block_Outbound_Vol = data["Block_Outbound_Vol"]
    Dist = data["Dist"]

    bay_size = _derive_bay_size_map(data)
    old_occupancy = _compute_old_occupancy(data)
    stable_free = {
        i: float(math.floor(min(
            max(0.0, float(I[i].get("cap", 0.0)) - float(old_occupancy.get((i, n), 0.0)))
            for n in N
        ) + eps))
        for i in I_list
    }

    alloc_boxes = {
        (i, j, s, n): 0.0
        for i in I_list
        for j in J_new
        for s in G
        for n in N
    }
    x_fix = {(i, j, n): 0.0 for i in I_list for j in J_new for n in N}

    n_order = list(N)
    prev_n = {}
    cum_arrivals = {(j, g): 0.0 for j in J_new for g in G}

    block_size_cap = {
        (k, s): sum(float(stable_free[i]) for i in Bays_in_Block[k] if int(bay_size[i]) == int(s))
        for k in K
        for s in data["S"]
    }

    def _block_score(j: str, k: str, s, n, used_cap: dict) -> tuple:
        size = _group_size(data, s)
        out_v = float(Block_Outbound_Vol[(k, n)])
        size_cap = max(float(block_size_cap[(k, size)]), eps)
        size_used = sum(
            float(used_cap[i])
            for i in Bays_in_Block[k]
            if int(bay_size[i]) == int(size)
        )
        used_ratio = size_used / size_cap
        return (1 if out_v > eps else 0, out_v, used_ratio, float(Dist[(j, k)]))

    for n in n_order:
        if prev_n:
            p = prev_n["n"]
            for i in I_list:
                for j in J_new:
                    for s in G:
                        alloc_boxes[(i, j, s, n)] = alloc_boxes[(i, j, s, p)]

        used_cap = {
            i: sum(float(alloc_boxes[(i, j, g, n)]) for j in J_new for g in G)
            for i in I_list
        }

        for j in J_new:
            selected_blocks = {
                I[i]["block"]
                for i in I_list
                if sum(float(alloc_boxes[(i, j, g, n)]) for g in G) > eps
            }

            for s in G:
                size = _group_size(data, s)
                cum_arrivals[(j, s)] += _arrival(data, j, s, n)
                need_stock = math.ceil(max(0.0, Alpha * cum_arrivals[(j, s)] - eps))
                current_stock = sum(float(alloc_boxes[(i, j, s, n)]) for i in I_list)
                add_need = max(0.0, float(need_stock) - current_stock)

                arr_n = _arrival(data, j, s, n)
                if arr_n > eps and current_stock <= eps and add_need <= eps:
                    add_need = 1.0

                if add_need <= eps:
                    continue

                made_progress = True
                while add_need > eps and made_progress:
                    made_progress = False
                    candidate_blocks = sorted(K, key=lambda k: _block_score(j, k, s, n, used_cap))
                    for k in candidate_blocks:
                        bays = [
                            i for i in Bays_in_Block[k]
                            if int(bay_size[i]) == int(size)
                            and math.floor(float(stable_free[i]) - used_cap[i] + eps) > 0
                        ]
                        bays.sort(key=lambda i: (-float(stable_free[i]) + used_cap[i], i))
                        for i in bays:
                            residual = float(
                                math.floor(float(stable_free[i]) - used_cap[i] + eps)
                            )
                            if residual <= eps:
                                continue
                            take = min(add_need, residual)
                            alloc_boxes[(i, j, s, n)] += take
                            used_cap[i] += take
                            selected_blocks.add(k)
                            made_progress = True
                            add_need -= take
                            if add_need <= eps:
                                break
                        if add_need <= eps:
                            break

                if add_need > 1e-6:
                    print(
                        f"[WarmStart] constructive start failed: insufficient group {s} capacity "
                        f"for {j} interval={n}, remaining={add_need:.2f}."
                    )
                    return None

            for i in I_list:
                if sum(float(alloc_boxes[(i, j, g, n)]) for g in G) > eps:
                    x_fix[(i, j, n)] = 1.0

        prev_n["n"] = n

    return {
        "alloc_boxes": alloc_boxes,
        "x": x_fix,
    }


def _build_fallback_warm_start(data: dict) -> dict:
    """
    Feasible MP start used when the avoid-outbound heuristic fails.

    It chooses as many blocks as needed for each ship, reserves box capacity in
    bays whose size mode matches the demand, and then fills each interval
    cumulatively. Capacity is based on the minimum remaining capacity over all
    intervals, so the start never relies on old outbound boxes being released
    later.
    """
    K = data['K']
    I = data['I']
    I_list = data['I_list']
    Bays_in_Block = data['Bays_in_Block']
    J_new = data['J_new']
    G = _new_groups(data)
    S = data['S']
    N = data['N']
    Alpha = data['Alpha']
    Fixed_Bay_Mode = data.get('Fixed_Bay_Mode', {})
    Fixed_Mode_Force = data['Fixed_Mode_Force']
    Dist = data.get('Dist', {})
    old_occupancy = _compute_old_occupancy(data)

    valid_sizes = {int(s) for s in S}
    bay_mode_map = {}
    for i in I_list:
        mode = Fixed_Bay_Mode.get(i)
        if mode is None:
            mode = I[i].get('fixed_size_ft')
        if mode is None:
            mode = next(
                (Fixed_Mode_Force.get((i, n)) for n in N if Fixed_Mode_Force.get((i, n)) is not None),
                40,
            )
        try:
            mode_int = int(mode)
        except Exception:
            mode_int = 40
        if mode_int not in valid_sizes and valid_sizes:
            mode_int = 40 if 40 in valid_sizes else sorted(valid_sizes)[0]
        bay_mode_map[i] = mode_int

    stable_free = {
        i: float(math.floor(min(
            max(0.0, float(I[i].get('cap', 0.0)) - float(old_occupancy.get((i, n), 0.0)))
            for n in N
        ) + 1e-9))
        for i in I_list
    }

    init_x = {(i, j, n): 0.0 for i in I_list for j in J_new for n in N}
    init_alloc = {(i, j, g, n): 0.0 for i in I_list for j in J_new for g in G for n in N}

    final_need = {}
    for j in J_new:
        for g in G:
            total = sum(_arrival(data, j, g, n) for n in N)
            final_need[(j, g)] = float(math.ceil(max(0.0, Alpha * total - 1e-9)))

    final_alloc = {(i, j, g): 0.0 for i in I_list for j in J_new for g in G}

    def _available_in_block(k, s_int):
        return sum(
            stable_free[i]
            for i in Bays_in_Block[k]
            if int(bay_mode_map[i]) == int(s_int)
        )

    def _combo_score(j, combo):
        dist_score = sum(float(Dist.get((j, k), 0.0)) for k in combo)
        leftover = 0.0
        for s_int in S:
            cap = sum(_available_in_block(k, s_int) for k in combo)
            need = sum(final_need[(j, g)] for g in G if int(_group_size(data, g)) == int(s_int))
            leftover += max(0.0, cap - need)
        return (len(combo), dist_score, leftover, tuple(combo))

    for j in J_new:
        feasible_combos = []
        for r in range(1, len(K) + 1):
            for combo in combinations(K, r):
                ok = True
                for s_int in S:
                    cap = sum(_available_in_block(k, s_int) for k in combo)
                    need = sum(final_need[(j, g)] for g in G if int(_group_size(data, g)) == int(s_int))
                    if cap + 1e-9 < need:
                        ok = False
                        break
                if ok:
                    feasible_combos.append(combo)
            if feasible_combos:
                break
        if not feasible_combos:
            raise RuntimeError(f"Fallback warm start cannot find enough stable capacity for {j}.")

        chosen_blocks = min(feasible_combos, key=lambda combo: _combo_score(j, combo))
        for g in G:
            s_int = _group_size(data, g)
            remaining = final_need[(j, g)]
            pool = [
                i for k in chosen_blocks for i in Bays_in_Block[k]
                if int(bay_mode_map[i]) == s_int and stable_free[i] > 1e-9
            ]
            for i in sorted(pool, key=lambda bay: (-stable_free[bay], bay)):
                take = min(stable_free[i], remaining)
                if take <= 1e-9:
                    continue
                final_alloc[(i, j, g)] = take
                stable_free[i] -= take
                remaining -= take
                if remaining <= 1e-9:
                    break
            if remaining > 1e-6:
                raise RuntimeError(f"Fallback warm start failed while assigning {j}, group {g}.")

    for j in J_new:
        cum_by_g = {g: 0.0 for g in G}
        for n in N:
            for g in G:
                cum_by_g[g] += _arrival(data, j, g, n)
                need = float(math.ceil(max(0.0, Alpha * cum_by_g[g] - 1e-9)))
                if need <= 1e-9:
                    continue
                pool = [
                    (i, final_alloc[(i, j, g)])
                    for i in I_list
                    if final_alloc[(i, j, g)] > 1e-9
                ]
                remaining = need
                for i, cap in sorted(pool, key=lambda item: (-item[1], item[0])):
                    take = min(cap, remaining)
                    if take <= 1e-9:
                        continue
                    init_alloc[(i, j, g, n)] = take
                    init_x[(i, j, n)] = 1.0
                    remaining -= take
                    if remaining <= 1e-9:
                        break
                if remaining > 1e-6:
                    raise RuntimeError(f"Fallback warm start cannot cover interval need for {j}, group {g}, n={n}.")

    return {'x': init_x, 'alloc_boxes': init_alloc}


# =====================================================================
# Destroy operators for ALNS
# =====================================================================
def _destroy_random(rng, current_x, n_destroy):
    """Random destroy: uniform sample of (i, j, n) keys."""
    all_keys = list(current_x.keys())
    n = min(n_destroy, len(all_keys))
    return set(rng.sample(all_keys, k=n))


def _destroy_active_biased(rng, current_x, n_destroy):
    """Bias toward currently-active (x=1) keys; mix in some inactive."""
    all_keys = list(current_x.keys())
    active = [k for k, v in current_x.items() if v > 0.5]
    n_act = min(len(active), max(1, int(0.7 * n_destroy)))
    pick = set(rng.sample(active, k=n_act)) if active else set()
    rem = n_destroy - len(pick)
    if rem > 0:
        pool = [k for k in all_keys if k not in pick]
        pick |= set(rng.sample(pool, k=min(rem, len(pool))))
    return pick


def _destroy_block_focused(rng, data, current_x, n_destroy):
    """Pick 1-2 random blocks; release all (i, j, n) for bays in those blocks."""
    K = data['K']
    Bays_in_Block = data['Bays_in_Block']
    J_new = data['J_new']
    N = data['N']

    n_blocks = max(1, min(len(K), rng.randint(1, 3)))
    blocks_chosen = rng.sample(list(K), k=n_blocks)
    bays_chosen = set()
    for k in blocks_chosen:
        bays_chosen.update(Bays_in_Block[k])

    pick = set()
    for i in bays_chosen:
        for j in J_new:
            for n in N:
                if (i, j, n) in current_x:
                    pick.add((i, j, n))
    if len(pick) < n_destroy:
        all_keys = list(current_x.keys())
        rem_pool = [k for k in all_keys if k not in pick]
        more = rng.sample(rem_pool, k=min(n_destroy - len(pick), len(rem_pool)))
        pick |= set(more)
    return pick


def _destroy_interval_focused(rng, data, current_x, n_destroy):
    """Pick 1-3 random consecutive intervals; release all (i, j, n) in them."""
    N = data['N']
    I_list = data['I_list']
    J_new = data['J_new']
    n_int = max(1, min(len(N), rng.randint(2, 4)))
    start = rng.randint(0, max(0, len(N) - n_int))
    intervals_chosen = list(N[start:start + n_int])

    pick = set()
    for i in I_list:
        for j in J_new:
            for n in intervals_chosen:
                if (i, j, n) in current_x:
                    pick.add((i, j, n))
    if len(pick) < n_destroy:
        all_keys = list(current_x.keys())
        rem_pool = [k for k in all_keys if k not in pick]
        more = rng.sample(rem_pool, k=min(n_destroy - len(pick), len(rem_pool)))
        pick |= set(more)
    return pick


def _destroy_ship_focused(rng, data, current_x, n_destroy):
    """Pick 1 ship; release all its (i, j, n) variables for full re-routing."""
    J_new = data['J_new']
    I_list = data['I_list']
    N = data['N']
    j_chosen = rng.choice(list(J_new))
    pick = set((i, j_chosen, n) for i in I_list for n in N if (i, j_chosen, n) in current_x)
    return pick


def _destroy_conflict_focused(rng, data, current_x, n_destroy):
    """Release blocks whose active assignments overlap high outbound workload."""
    K = data['K']
    N = data['N']
    J_new = data['J_new']
    Bays_in_Block = data['Bays_in_Block']
    block_out = data.get('Block_Outbound_Vol', {})

    scored = []
    for k in K:
        bays = set(Bays_in_Block[k])
        active_count = sum(
            1
            for (i, _j, _n), v in current_x.items()
            if i in bays and float(v) > 0.5
        )
        out_total = sum(float(block_out.get((k, n), 0.0)) for n in N)
        scored.append((out_total * (1.0 + active_count), k))
    scored.sort(reverse=True)
    if not scored:
        return _destroy_random(rng, current_x, n_destroy)

    pool = [k for _score, k in scored[:max(1, min(len(scored), 4))]]
    n_blocks = max(1, min(len(pool), rng.randint(1, 2)))
    blocks_chosen = set(rng.sample(pool, k=n_blocks))
    pick = set()
    for k in blocks_chosen:
        for i in Bays_in_Block[k]:
            for j in J_new:
                for n in N:
                    if (i, j, n) in current_x:
                        pick.add((i, j, n))
    if len(pick) < n_destroy:
        all_keys = list(current_x.keys())
        rem_pool = [k for k in all_keys if k not in pick]
        pick |= set(rng.sample(rem_pool, k=min(n_destroy - len(pick), len(rem_pool))))
    return pick


def _destroy_distance_focused(rng, data, current_x, n_destroy):
    """Release active bay-ship-interval keys with high ship-block distance."""
    I = data['I']
    Dist = data.get('Dist', {})
    active_scored = []
    for key, val in current_x.items():
        if float(val) <= 0.5:
            continue
        i, j, _n = key
        k = I[i]['block']
        active_scored.append((float(Dist.get((j, k), 0.0)), key))
    if not active_scored:
        return _destroy_random(rng, current_x, n_destroy)
    active_scored.sort(reverse=True)
    top_n = max(1, min(len(active_scored), max(n_destroy, int(0.35 * len(active_scored)))))
    pool = [key for _score, key in active_scored[:top_n]]
    pick = set(rng.sample(pool, k=min(n_destroy, len(pool))))
    if len(pick) < n_destroy:
        all_keys = list(current_x.keys())
        rem_pool = [k for k in all_keys if k not in pick]
        pick |= set(rng.sample(rem_pool, k=min(n_destroy - len(pick), len(rem_pool))))
    return pick


def _select_operator(rng, weights_dict):
    """Roulette-wheel selection by adaptive weights."""
    total = sum(weights_dict.values())
    if total <= 1e-9:
        return rng.choice(list(weights_dict.keys()))
    r = rng.uniform(0, total)
    acc = 0.0
    for op, w in weights_dict.items():
        acc += w
        if r <= acc:
            return op
    return list(weights_dict.keys())[-1]


# =====================================================================
# Master v2: lifts balance/conflict into master via in_share auxiliary
# =====================================================================
def build_master_v2(
    data: dict,
    weights: Weights,
    include_attribute_helpers: bool = False,
    alloc_domain: str = "integer",
):
    """
    Master with the cross-ship coupling lifted into auxiliary continuous
    variables:
      - in_share[j,k,n]: ship j's total inbound to block k at interval n
      - in_total[k,n]:  sum_j,s in_share[j,k,s,n] + fixed_in_block[k,n]
      - avg[n]:         (sum_k in_total[k,n]) / |K|
      - g[k,n]:         exact L1 absolute deviation |in_total[k,n] - avg[n]|
      - distance cost:  exact linear term on in_share[j,k,s,n]

    Master objective:
      master_x * sum x * dur                      (open-bay cost)
    + sub_balance * sum g[k,n]                     (exact L1 balance)
    + sub_conflict * sum out_vol[k,n] * in_total[k,n]  (conflict, exact linear)
    + sub_dist * sum Dist[j,k] * in_share[j,k,s,n] (distance, exact linear)

    The master also keeps cumulative local block-size capacity links as a
    strengthening layer.  SP_j still checks bay-level feasibility and can
    generate cuts for remaining pattern infeasibilities.
    """
    K = data['K']
    I = data['I']
    I_list = data['I_list']
    J_new = data['J_new']
    S = data['S']
    G = _new_groups(data)
    N = data['N']
    Alpha = data['Alpha']
    Dist = data['Dist']

    Fixed_Bay_Mode = data.get('Fixed_Bay_Mode', {})
    Fixed_Mode_Force = data['Fixed_Mode_Force']
    Intervals = data['Intervals']
    Bays_in_Block = data['Bays_in_Block']

    m = gp.Model("MP_master_v2")
    m.Params.OutputFlag = 0
    m.Params.DualReductions = 0
    m.Params.InfUnbdInfo = 1
    m.Params.LazyConstraints = 1

    # Original first-stage variables
    if alloc_domain not in {"integer", "continuous"}:
        raise ValueError("alloc_domain must be 'integer' or 'continuous'")
    alloc_type = GRB.INTEGER if alloc_domain == "integer" else GRB.CONTINUOUS
    alloc_boxes = m.addVars(I_list, J_new, G, N, vtype=alloc_type, lb=0, name="alloc_boxes")
    x = m.addVars(I_list, J_new, N, vtype=GRB.BINARY, name="x")
    block_use_new = m.addVars(K, J_new, N, vtype=GRB.BINARY, name="block_use_new")

    # NEW lifted variables (continuous, LP-relax friendly).
    # in_share is PER-SIZE so master's allocation is size-aware and aligns
    # with SP_j's per-size constraints (link_box_cap, fixed_mode bays).
    in_share = m.addVars(J_new, K, G, N, lb=0.0, name="in_share")
    in_total = m.addVars(K, N, lb=0.0, name="in_total")          # block k total inbound at n
    avg_n = m.addVars(N, lb=0.0, name="avg_bal")
    g_bal = m.addVars(K, N, lb=0.0, name="g_bal")                # |in_total - avg|

    # Bay mode map (same as v1)
    valid_sizes = {int(s) for s in S}
    bay_mode_map = {}
    for i in I_list:
        mode = Fixed_Bay_Mode.get(i)
        if mode is None:
            mode = I[i].get('fixed_size_ft')
        if mode is None:
            mode = next(
                (Fixed_Mode_Force.get((i, n)) for n in N if Fixed_Mode_Force.get((i, n)) is not None),
                40,
            )
        try:
            mode_int = int(mode)
        except Exception:
            mode_int = 40
        if mode_int not in valid_sizes and valid_sizes:
            mode_int = 40 if 40 in valid_sizes else sorted(valid_sizes)[0]
        bay_mode_map[i] = mode_int
    bays_by_size = {
        int(s): [i for i in I_list if int(bay_mode_map[i]) == int(s)]
        for s in S
    }

    # Constants: fixed (J_old) inbound contribution per block-interval
    fixed_in_block = _fixed_in_block(data)
    old_occupancy = _compute_old_occupancy(data)
    remaining_cap = {
        (i, n): max(0.0, float(I[i].get('cap', 0.0)) - float(old_occupancy.get((i, n), 0.0)))
        for i in I_list for n in N
    }

    # ========== Original first-stage constraints (same as v1) ==========
    for i in I_list:
        for n in N:
            fixed_size = int(bay_mode_map[i])
            for g in G:
                if _group_size(data, g) != fixed_size:
                    m.addConstr(alloc_boxes.sum(i, '*', g, n) == 0,
                                name=f"fixed_mode_zero_{i}_{g}_{n}")
                else:
                    m.addConstr(alloc_boxes.sum(i, '*', g, n) <= remaining_cap[(i, n)],
                                name=f"fixed_mode_cap_{i}_{g}_{n}")

    for i in I_list:
        for n in N:
            for j in J_new:
                m.addConstr(alloc_boxes.sum(i, j, '*', n) <= remaining_cap[(i, n)] * x[i, j, n])
                m.addConstr(x[i, j, n] <= alloc_boxes.sum(i, j, '*', n))
            if n > 0:
                for j in J_new:
                    for g in G:
                        m.addConstr(alloc_boxes[i, j, g, n] >= alloc_boxes[i, j, g, n - 1])

    for i in I_list:
        for n in N:
            new_boxes = gp.quicksum(alloc_boxes[i, j, g, n] for j in J_new for g in G)
            m.addConstr(new_boxes <= remaining_cap[(i, n)], name=f"new_cap_{i}_{n}")

    for j in J_new:
        for n in N:
            dur = Intervals[n]['dur']
            for s in S:
                s_int = int(s)
                rhs_arr_size = sum(_arrival(data, j, g, n) for g in G if _group_size(data, g) == s_int)
                if rhs_arr_size <= 1e-9:
                    continue
                size_bays = bays_by_size.get(s_int, [])
                m.addConstr(
                    gp.quicksum(float(data['Bay_Handling_Rate'][(i, n)]) * dur * x[i, j, n] for i in size_bays)
                    >= Alpha * rhs_arr_size,
                    name=f"nec_workcap_size_{j}_{s_int}_{n}",
                )
                max_work = max(
                    (float(data['Bay_Handling_Rate'][(i, n)]) * dur for i in size_bays),
                    default=0.0,
                )
                min_work_bays = int(math.ceil((Alpha * rhs_arr_size - 1e-9) / max_work)) if max_work > 1e-9 else 0
                if min_work_bays > 0:
                    m.addConstr(
                        gp.quicksum(x[i, j, n] for i in size_bays) >= min_work_bays,
                        name=f"min_work_bays_size_{j}_{s_int}_{n}",
                    )
            for g in G:
                rhs_arr = _arrival(data, j, g, n)
                if rhs_arr > 1e-9:
                    size = _group_size(data, g)
                    m.addConstr(
                        gp.quicksum(float(data['Bay_Handling_Rate'][(i, n)]) * dur * x[i, j, n] for i in bays_by_size[int(size)]) >= Alpha * rhs_arr,
                        name=f"nec_workcap_{j}_{g}_{n}"
                    )
                    max_work = max(
                        (float(data['Bay_Handling_Rate'][(i, n)]) * dur for i in bays_by_size[int(size)]),
                        default=0.0,
                    )
                    min_work_bays = int(math.ceil((Alpha * rhs_arr - 1e-9) / max_work)) if max_work > 1e-9 else 0
                    if min_work_bays > 0:
                        m.addConstr(
                            gp.quicksum(x[i, j, n] for i in bays_by_size[int(size)]) >= min_work_bays,
                            name=f"min_work_bays_{j}_{g}_{n}",
                        )
            # NOTE: ub_open_bays intentionally OMITTED (lazy cuts tighten naturally).

    for j in J_new:
        for s in S:
            s_int = int(s)
            cum_size = 0.0
            for n in N:
                cum_size += sum(_arrival(data, j, g, n) for g in G if _group_size(data, g) == s_int)
                if cum_size <= 1e-9:
                    continue
                max_store = max(
                    (remaining_cap[(i, n)] for i in bays_by_size.get(s_int, [])),
                    default=0.0,
                )
                min_store_bays = int(math.ceil((Alpha * cum_size - 1e-9) / max_store)) if max_store > 1e-9 else 0
                if min_store_bays > 0:
                    m.addConstr(
                        gp.quicksum(x[i, j, n] for i in bays_by_size.get(s_int, [])) >= min_store_bays,
                        name=f"min_store_bays_{j}_{s_int}_{n}",
                    )
        for g in G:
            cum = 0.0
            for n in N:
                cum += _arrival(data, j, g, n)
                if cum > 1e-9:
                    size = _group_size(data, g)
                    m.addConstr(
                        gp.quicksum(alloc_boxes[i, j, g, n] for i in bays_by_size[int(size)]) >= Alpha * cum,
                        name=f"nec_boxcap_{j}_{g}_{n}"
                    )

    for j in J_new:
        for n in N:
            for k in K:
                bays = Bays_in_Block[k]
                m.addConstr(
                    gp.quicksum(x[i, j, n] for i in bays) <= len(bays) * block_use_new[k, j, n],
                    name=f"link_block_use_{k}_{j}_{n}",
                )
                m.addConstr(
                    block_use_new[k, j, n] <= gp.quicksum(x[i, j, n] for i in bays),
                    name=f"link_block_use_reverse_{k}_{j}_{n}",
                )

    # ========== NEW: per-size in_share constraints ==========
    # 1. Per-size sum equals per-size arrivals (split across blocks)
    for j in J_new:
        for g in G:
            for n in N:
                arr_jsn = _arrival(data, j, g, n)
                m.addConstr(
                    gp.quicksum(in_share[j, k, g, n] for k in K) == arr_jsn,
                    name=f"in_share_arrivals_{j}_{g}_{n}"
                )

    # 2. block_use_new gating: in_share to block k requires the ship uses block k
    for j in J_new:
        for k in K:
            for n in N:
                # Ship j's total arrivals at interval n (used as upper bound)
                arr_jn_total = sum(_arrival(data, j, g, n) for g in G)
                if arr_jn_total > 1e-9:
                    m.addConstr(
                        gp.quicksum(in_share[j, k, g, n] for g in G)
                        <= arr_jn_total * block_use_new[k, j, n],
                        name=f"in_share_block_link_{j}_{k}_{n}"
                    )

    # 3. PER-SIZE work-cap link: only bays of mode s can take size-s inbound.
    #    The cumulative in_share-to-alloc capacity link is intentionally left
    #    to SP_j's link_in_share + link_box_cap constraints, so mismatched
    #    block-level flow and bay-level inventory produce Farkas cuts.
    for j in J_new:
        for k in K:
            for s in S:
                s_int = int(s)
                size_groups = [g for g in G if _group_size(data, g) == s_int]
                bays_in_block_of_size = [
                    i for i in Bays_in_Block[k] if int(bay_mode_map[i]) == s_int
                ]
                for n in N:
                    if bays_in_block_of_size:
                        dur = Intervals[n]['dur']
                        m.addConstr(
                            Alpha * gp.quicksum(in_share[j, k, g, n] for g in size_groups)
                            <= gp.quicksum(
                                float(data['Bay_Handling_Rate'][(i, n)]) * dur * x[i, j, n]
                                for i in bays_in_block_of_size
                            ),
                            name=f"per_size_work_cap_agg_{j}_{k}_{s_int}_{n}",
                        )
                    else:
                        for g in size_groups:
                            m.addConstr(
                                in_share[j, k, g, n] == 0,
                                name=f"per_size_no_bay_agg_{j}_{k}_{g}_{n}",
                            )
            for g in G:
                s_int = _group_size(data, g)
                for n in N:
                    bays_in_block_of_size = [
                        i for i in Bays_in_Block[k] if int(bay_mode_map[i]) == s_int
                    ]
                    dur = Intervals[n]['dur']
                    if bays_in_block_of_size:
                        m.addConstr(
                            Alpha * in_share[j, k, g, n]
                            <= gp.quicksum(float(data['Bay_Handling_Rate'][(i, n)]) * dur * x[i, j, n]
                                          for i in bays_in_block_of_size),
                            name=f"per_size_work_cap_{j}_{k}_{g}_{n}"
                        )
                    else:
                        m.addConstr(
                            in_share[j, k, g, n] == 0,
                            name=f"per_size_no_bay_{j}_{k}_{g}_{n}",
                        )

    for j in J_new:
        for k in K:
            for g in G:
                s_int = _group_size(data, g)
                bays_in_block_of_size = [
                    i for i in Bays_in_Block[k] if int(bay_mode_map[i]) == s_int
                ]
                if not bays_in_block_of_size:
                    continue
                for n in N:
                    cum_share = gp.quicksum(
                        in_share[j, k, g, nn] for nn in N if nn <= n
                    )
                    cum_alloc = gp.quicksum(
                        alloc_boxes[i, j, g, n] for i in bays_in_block_of_size
                    )
                    m.addConstr(
                        Alpha * cum_share <= cum_alloc,
                        name=f"local_per_size_box_cap_{j}_{k}_{g}_{n}",
                    )

    # 4. in_total[k,n] = sum_{j,s} in_share[j,k,s,n] + fixed_in_block
    for k in K:
        for n in N:
            m.addConstr(
                in_total[k, n]
                == gp.quicksum(in_share[j, k, g, n] for j in J_new for g in G)
                   + fixed_in_block[(k, n)],
                name=f"in_total_def_{k}_{n}"
            )

    # avg definition
    K_len = float(len(K))
    for n in N:
        m.addConstr(
            K_len * avg_n[n] == in_total.sum('*', n),
            name=f"avg_def_{n}"
        )

    # Exact L1 balance: g[k,n] = |in_total[k,n] - avg[n]| at optimum.
    for n in N:
        for k in K:
            z = in_total[k, n] - avg_n[n]
            m.addConstr(g_bal[k, n] >= z, name=f"l1_bal_pos_{k}_{n}")
            m.addConstr(g_bal[k, n] >= -z, name=f"l1_bal_neg_{k}_{n}")

    # ========== Objective ==========
    scales = _objective_scales(data)
    pressure = _outbound_pressure(data)

    obj_x_raw = gp.quicksum(
        x[i, j, n] * Intervals[n]['dur']
        for i in I_list for j in J_new for n in N
    )
    obj_balance = gp.quicksum(g_bal[k, n] for k in K for n in N)
    obj_conflict = gp.LinExpr()
    for n in N:
        for k in K:
            out_vol = float(pressure[(k, n)])
            if out_vol > 1e-9:
                new_in = gp.quicksum(in_share[j, k, g, n] for j in J_new for g in G)
                obj_conflict += out_vol * new_in
    obj_distance = gp.quicksum(
        float(Dist[(j, k)]) * in_share[j, k, g, n]
        for j in J_new for k in K for g in G for n in N
    )

    pod_block_use = {}
    weight_block_use = {}
    bay_height_used = {}
    bay_height_mix = {}
    final_n = max(N) if N else 0
    pod_values = _attribute_values(data, "pod")
    if include_attribute_helpers and pod_values:
        pod_block_use = m.addVars(J_new, pod_values, K, vtype=GRB.BINARY, name="pod_block_use")
        for j in J_new:
            for pod in pod_values:
                total_need = Alpha * sum(_arrival(data, j, g, n) for g in G if _group_attr(data, g, "pod") == pod for n in N)
                pod_sizes = {
                    _group_size(data, g)
                    for g in G
                    if _group_attr(data, g, "pod") == pod
                }
                if total_need <= 1e-9:
                    for k in K:
                        m.addConstr(pod_block_use[j, pod, k] == 0, name=f"pod_unused_{j}_{pod}_{k}")
                    continue
                for k in K:
                    block_cap = sum(
                        remaining_cap[(i, final_n)]
                        for i in Bays_in_Block[k]
                        if int(bay_mode_map[i]) in pod_sizes
                    )
                    big_m = min(float(total_need), float(block_cap))
                    if big_m <= 1e-9:
                        m.addConstr(pod_block_use[j, pod, k] == 0, name=f"pod_no_cap_{j}_{pod}_{k}")
                        continue
                    m.addConstr(
                        gp.quicksum(
                            alloc_boxes[i, j, g, final_n]
                            for i in Bays_in_Block[k]
                            for g in G
                            if _group_attr(data, g, "pod") == pod
                        )
                        <= big_m * pod_block_use[j, pod, k],
                        name=f"pod_block_link_{j}_{pod}_{k}",
                    )
    weight_values = _attribute_values(data, "weight_class")
    if include_attribute_helpers and weight_values:
        weight_block_use = m.addVars(J_new, weight_values, K, vtype=GRB.BINARY, name="weight_block_use")
        for j in J_new:
            for weight_class in weight_values:
                total_need = Alpha * sum(_arrival(data, j, g, n) for g in G if _group_attr(data, g, "weight_class") == weight_class for n in N)
                weight_sizes = {
                    _group_size(data, g)
                    for g in G
                    if _group_attr(data, g, "weight_class") == weight_class
                }
                if total_need <= 1e-9:
                    for k in K:
                        m.addConstr(weight_block_use[j, weight_class, k] == 0, name=f"weight_unused_{j}_{weight_class}_{k}")
                    continue
                for k in K:
                    block_cap = sum(
                        remaining_cap[(i, final_n)]
                        for i in Bays_in_Block[k]
                        if int(bay_mode_map[i]) in weight_sizes
                    )
                    big_m = min(float(total_need), float(block_cap))
                    if big_m <= 1e-9:
                        m.addConstr(weight_block_use[j, weight_class, k] == 0, name=f"weight_no_cap_{j}_{weight_class}_{k}")
                        continue
                    m.addConstr(
                        gp.quicksum(
                            alloc_boxes[i, j, g, final_n]
                            for i in Bays_in_Block[k]
                            for g in G
                            if _group_attr(data, g, "weight_class") == weight_class
                        )
                        <= big_m * weight_block_use[j, weight_class, k],
                        name=f"weight_block_link_{j}_{weight_class}_{k}",
                    )
    height_values = _attribute_values(data, "height")
    if include_attribute_helpers and height_values:
        bay_height_used = m.addVars(I_list, height_values, N, vtype=GRB.BINARY, name="bay_height_used")
        bay_height_mix = m.addVars(I_list, N, lb=0.0, name="bay_height_mix")
        for i in I_list:
            for n in N:
                for height in height_values:
                    for j in J_new:
                        for g in G:
                            if _group_attr(data, g, "height") != height:
                                continue
                            m.addConstr(
                                alloc_boxes[i, j, g, n]
                                <= remaining_cap[(i, n)] * bay_height_used[i, height, n],
                                name=f"height_use_link_{i}_{height}_{j}_{g}_{n}",
                            )
                m.addConstr(
                    bay_height_mix[i, n]
                    >= gp.quicksum(bay_height_used[i, height, n] for height in height_values) - 1.0,
                    name=f"height_mix_soft_{i}_{n}",
                )
    obj_expr = (
        weights.master.x * obj_x_raw / scales["open"]
        + weights.sub.balance * obj_balance / scales["balance"]
        + weights.sub.conflict * obj_conflict / scales["conflict"]
        + weights.sub.dist * obj_distance / scales["distance"]
    )
    m.setObjective(_objective_scale_factor(weights) * obj_expr, GRB.MINIMIZE)
    m.update()
    return m, {
        'alloc_boxes': alloc_boxes,
        'x': x,
        'block_use_new': block_use_new,
        'in_share': in_share,
        'in_total': in_total,
        'avg_n': avg_n,
        'g_bal': g_bal,
        'pod_block_use': pod_block_use,
        'weight_block_use': weight_block_use,
        'bay_height_used': bay_height_used,
        'bay_height_mix': bay_height_mix,
        'balance_objective_mode': 'l1',
        'fixed_in_block': fixed_in_block,
        'outbound_pressure': pressure,
        'objective_scales': scales,
        'old_occupancy': old_occupancy,
        'remaining_cap': remaining_cap,
        'bay_mode_map': bay_mode_map,
        'bays_by_size': bays_by_size,
    }


# =====================================================================
# Per-ship SP LP
# =====================================================================
def build_and_solve_sp_per_ship_lp(
    data: dict,
    mp_fix: dict,
    weights: Weights,
    j: str,
    verbose: bool = False,
):
    """
    Solve the per-ship LP subproblem for new ship j:

        min  sum_{s,i,n} din[s,i,n] * Dist(j, block(i))
        s.t. inv balance for ship j
             arrivals: sum_i din[s,i,n] = Arrivals[(j,s,n)]
             link_box_cap: Alpha * inv[s,i,n] <= alloc_fix[i,j,s,n]
             link_work:    Alpha * sum_s din[s,i,n] <= cap * dur * x_fix[i,j,n]
             in_share equality: sum_{i in block_k} din[s,i,n] = in_share_fix[j,k,s,n]

    Returns (sp, ctx) where ctx['link_box_cap'], ['link_work'], ['link_in_share']
    are the constraint handles. The dual `c.Pi` of each linking constraint is
    ready to be read after sp.optimize().
    """
    K = data['K']
    I = data['I']
    I_list = data['I_list']
    Bays_in_Block = data['Bays_in_Block']
    G = _new_groups(data)
    N = data['N']
    Alpha = data['Alpha']
    Intervals = data['Intervals']
    initial_inventory_data = data['initial_inventory_data']
    Dist = data['Dist']
    old_occupancy = _compute_old_occupancy(data)
    scales = _objective_scales(data)

    sp = gp.Model(f"SP_v2_{j}")
    sp.Params.OutputFlag = 1 if verbose else 0
    sp.Params.LogToConsole = 1 if verbose else 0
    sp.Params.DualReductions = 0
    sp.Params.InfUnbdInfo = 1
    sp.Params.Method = 1   # dual simplex for LP

    # Variables: only for ship j
    din = sp.addVars(G, I_list, N, lb=0.0, name="din")
    inv = sp.addVars(G, I_list, N, lb=0.0, name="inv")

    # ---- inv balance ----
    for s in G:
        for i in I_list:
            init_inv = float(initial_inventory_data.get((i, j, s), 0.0))
            for n in N:
                prev = inv[s, i, n - 1] if n > 0 else init_inv
                sp.addConstr(
                    inv[s, i, n] == prev + din[s, i, n],
                    name=f"bal_{s}_{i}_{n}"
                )

    # ---- arrivals ----
    for s in G:
        for n in N:
            sp.addConstr(
                gp.quicksum(din[s, i, n] for i in I_list)
                == _arrival(data, j, s, n),
                name=f"arr_{s}_{n}"
            )

    # ---- link_box_cap (uses alloc_fix from master) ----
    link_box_cap = {}
    for i in I_list:
        for n in N:
            for s in G:
                rhs = float(mp_fix['alloc_boxes'][(i, j, s, n)])
                c = sp.addConstr(
                    Alpha * inv[s, i, n] <= rhs,
                    name=f"link_box_cap_{i}_{s}_{n}"
                )
                link_box_cap[(i, j, s, n)] = c

    # ---- link_work (uses x_fix from master) ----
    link_work = {}
    for i in I_list:
        for n in N:
            dur = float(Intervals[n]['dur'])
            rem_cap = max(0.0, float(I[i]['cap']) - float(old_occupancy.get((i, n), 0.0)))
            rhs = rem_cap * dur * float(mp_fix['x'][(i, j, n)])
            c = sp.addConstr(
                Alpha * gp.quicksum(din[s, i, n] for s in G) <= rhs,
                name=f"link_work_{i}_{n}"
            )
            link_work[(i, j, n)] = c

    # ---- link_in_share: PER-SIZE coupling SP din to master's in_share. ----
    # sum_{i in block_k} din[s,i,n] = in_share_fix[j,k,s,n]
    link_in_share = {}
    for k in K:
        bays = Bays_in_Block[k]
        for s in G:
            for n in N:
                rhs = float(mp_fix['in_share'][(j, k, s, n)])
                c = sp.addConstr(
                    gp.quicksum(din[s, i, n] for i in bays) == rhs,
                    name=f"link_in_share_{k}_{s}_{n}"
                )
                link_in_share[(j, k, s, n)] = c

    # ---- Objective: distance only ----
    obj_dist = gp.quicksum(
        din[s, i, n] * float(Dist[(j, I[i]['block'])])
        for s in G for i in I_list for n in N
    )
    sp.setObjective(
        _objective_scale_factor(weights) * weights.sub.dist * obj_dist / scales["distance"],
        GRB.MINIMIZE,
    )
    sp.update()
    sp.optimize()

    ctx = {
        'din': din, 'inv': inv,
        'link_box_cap': link_box_cap,
        'link_work': link_work,
        'link_in_share': link_in_share,
        'sp_obj': float(sp.ObjVal) if sp.Status == GRB.OPTIMAL else None,
    }
    return sp, ctx


def _linexpr_value(expr: gp.LinExpr, get_value) -> float:
    val = float(expr.getConstant())
    for idx in range(expr.size()):
        val += float(expr.getCoeff(idx)) * float(get_value(expr.getVar(idx)))
    return val


def _build_farkas_feasibility_cut_v2(data: dict, mp_vars: dict, sp_j, sp_j_ctx: dict):
    """
    Build a globally valid feasibility cut from an infeasible per-ship SP.

    Returns (lin_expr, rhs) so the callback can add lin_expr >= rhs.
    """
    farkas_lin = gp.LinExpr()
    farkas_const = 0.0
    old_occupancy = _compute_old_occupancy(data)

    for (i, jj, s, n), c in sp_j_ctx['link_box_cap'].items():
        fd = float(getattr(c, 'FarkasDual', 0.0) or 0.0)
        if abs(fd) < 1e-9:
            continue
        farkas_lin += fd * mp_vars['alloc_boxes'][i, jj, s, n]

    for (i, jj, n), c in sp_j_ctx['link_work'].items():
        fd = float(getattr(c, 'FarkasDual', 0.0) or 0.0)
        if abs(fd) < 1e-9:
            continue
        rem_cap = max(0.0, float(data['I'][i]['cap']) - float(old_occupancy.get((i, n), 0.0)))
        cap_dur = rem_cap * float(data['Intervals'][n]['dur'])
        farkas_lin += fd * (cap_dur * mp_vars['x'][i, jj, n])

    for key, c in sp_j_ctx['link_in_share'].items():
        fd = float(getattr(c, 'FarkasDual', 0.0) or 0.0)
        if abs(fd) < 1e-9:
            continue
        if len(key) == 4:
            jj, k, ss, nn = key
            farkas_lin += fd * mp_vars['in_share'][jj, k, ss, nn]
        else:
            jj, k, nn = key
            for ss in _new_groups(data):
                farkas_lin += fd * mp_vars['in_share'][jj, k, ss, nn]

    for c in sp_j.getConstrs():
        fd = float(getattr(c, 'FarkasDual', 0.0) or 0.0)
        if abs(fd) < 1e-9:
            continue
        cname = c.ConstrName
        if cname.startswith("arr_") or cname.startswith("bal_"):
            farkas_const += fd * float(c.RHS)

    return farkas_lin, -farkas_const


# =====================================================================
# Helper: extract MP fix from incumbent (callback) or full model (post-solve)
# =====================================================================
def _extract_mp_fix_v2(mp_vars: dict, get_value):
    """get_value: function (var) -> float (cbGetSolution or var.X)."""
    return {
        'x': {k: float(get_value(v)) for k, v in mp_vars['x'].items()},
        'alloc_boxes': {k: float(get_value(v)) for k, v in mp_vars['alloc_boxes'].items()},
        'in_share': {k: float(get_value(v)) for k, v in mp_vars['in_share'].items()},
    }


def solve_benders_bbc_v2(
    data: dict,
    weights: Weights,
    *,
    time_limit_s: float | None = None,
    mip_gap: float = 0.01,
    cut_violation_tol: float = 1e-4,
    use_warm_start: bool = True,
    initial_mp_fix: Optional[dict] = None,
    use_node_cuts: bool = True,
    node_cut_limit: int = 250,
    reported_gap_stop: float | None = None,
    min_runtime_s: float = 0.0,
    feasibility_cut_stall_time_s: float | None = None,
    lb_stall_time_s: float | None = None,
    lb_stall_min_time_s: float = 10.0,
    lb_stall_gap_guard: float | None = None,
    lb_improve_tol: float = 1e-4,
    gurobi_params: dict | None = None,
    verbose: bool = True,
):
    """
    Branch-and-Benders-Cut v2: per-ship SP LP + feasibility cuts.

    Differences vs v1:
      - Master holds in_share, in_total, avg, g_bal aux variables.
      - SP is now per-ship LP (no balance^2, no conflict; those are in master).
      - Each MIPSOL incumbent is checked by |J_new| SP solves.
      - Infeasible ship-level patterns generate Farkas/no-good cuts.
    """
    K = data['K']
    J_new = data['J_new']
    N = data['N']

    mp, mp_vars = build_master_v2(data, weights)
    if time_limit_s is not None:
        mp.Params.TimeLimit = float(time_limit_s)
    mp.Params.MIPGap = float(mip_gap)
    node_cuts_enabled = bool(use_node_cuts)
    if node_cuts_enabled:
        mp.Params.PreCrush = 1
    if verbose:
        mp.Params.OutputFlag = 1
    if gurobi_params:
        for param_name, param_value in gurobi_params.items():
            try:
                mp.setParam(str(param_name), param_value)
            except Exception:
                if verbose:
                    print(f"[BBC-v2] ignored invalid Gurobi parameter {param_name}={param_value}")

    # ---- Warm start ----
    init_stats = {'warm_start_ok': False, 'init_sp_obj': None, 'init_cuts': 0}
    if use_warm_start or initial_mp_fix is not None:
        init_fix = None
        if initial_mp_fix is not None:
            init_fix = {
                'x': dict(initial_mp_fix.get('x', {})),
                'alloc_boxes': dict(initial_mp_fix.get('alloc_boxes', {})),
                'in_share': dict(initial_mp_fix.get('in_share', {})),
            }
        else:
            try:
                init_fix = _build_fallback_warm_start(data)
            except Exception:
                init_fix = None
            if init_fix is None:
                try:
                    init_fix = _construct_avoid_outbound_initial_mp_fix(
                        data=data, weights=weights,
                    )
                except Exception:
                    init_fix = None

        if init_fix is not None:
            # Per-size in_share warm start: build a bay-level flow that is
            # feasible for SP_j, then aggregate it back to block-size shares.
            in_share_warm = {}
            Bays_in_Block = data['Bays_in_Block']
            S = data['S']
            G = _new_groups(data)
            provided_in_share = dict(init_fix.get('in_share', {}))
            provided_in_share_complete = (
                initial_mp_fix is not None
                and all((j, k, g, n) in provided_in_share for j in J_new for k in K for g in G for n in N)
            )
            Alpha = float(data['Alpha'])
            Intervals = data['Intervals']
            initial_inventory_data = data['initial_inventory_data']
            old_occupancy = _compute_old_occupancy(data)
            # Determine bay mode (replicate from master)
            valid_sizes = {int(s) for s in S}
            Fixed_Bay_Mode = data.get('Fixed_Bay_Mode', {})
            Fixed_Mode_Force = data['Fixed_Mode_Force']
            bay_mode_init = {}
            for i in data['I_list']:
                mode = Fixed_Bay_Mode.get(i)
                if mode is None:
                    mode = data['I'][i].get('fixed_size_ft')
                if mode is None:
                    mode = next(
                        (Fixed_Mode_Force.get((i, n)) for n in N if Fixed_Mode_Force.get((i, n)) is not None),
                        40,
                    )
                try:
                    mode_int = int(mode)
                except Exception:
                    mode_int = 40
                if mode_int not in valid_sizes and valid_sizes:
                    mode_int = 40 if 40 in valid_sizes else sorted(valid_sizes)[0]
                bay_mode_init[i] = mode_int

            bay_to_block = {
                i: k for k in K for i in Bays_in_Block[k]
            }
            cum_din_warm = {
                (j, g, i): float(initial_inventory_data.get((i, j, g), 0.0))
                for j in J_new for g in G for i in data['I_list']
            }
            for j in J_new:
                for n in N:
                    for s in G:
                        arr_left = _arrival(data, j, s, n)
                        for k in K:
                            in_share_warm[(j, k, s, n)] = 0.0
                        bay_room = []
                        size = _group_size(data, s)
                        for i in data['I_list']:
                            if int(bay_mode_init[i]) != int(size):
                                continue
                            alloc_room = (
                                float(init_fix['alloc_boxes'].get((i, j, s, n), 0.0)) / Alpha
                                - cum_din_warm[(j, s, i)]
                            )
                            rem_cap = max(
                                0.0,
                                float(data['I'][i]['cap'])
                                - float(old_occupancy.get((i, n), 0.0)),
                            )
                            work_room = (
                                rem_cap
                                * float(Intervals[n]['dur'])
                                * float(init_fix['x'].get((i, j, n), 0.0))
                                / Alpha
                            )
                            room = min(max(0.0, alloc_room), max(0.0, work_room))
                            if room > 1e-9:
                                bay_room.append((i, room))
                        for i, room in sorted(bay_room, key=lambda item: (-item[1], item[0])):
                            take = min(arr_left, room)
                            if take <= 1e-9:
                                continue
                            k = bay_to_block[i]
                            in_share_warm[(j, k, s, n)] += take
                            cum_din_warm[(j, s, i)] += take
                            arr_left -= take
                            if arr_left <= 1e-9:
                                break
                        if arr_left > 1e-6:
                            # Keep the MIP start complete, but mark the warm SP
                            # check below as the source of truth.
                            feasible_blocks = [
                                bay_to_block[i] for i, _ in bay_room
                            ] or list(K)
                            share_each = arr_left / float(len(feasible_blocks))
                            for k in feasible_blocks:
                                in_share_warm[(j, k, s, n)] += share_each
            init_fix['in_share'] = in_share_warm
            if provided_in_share_complete:
                init_fix['in_share'] = provided_in_share

            # Set Var.Start
            try:
                for key, var in mp_vars['x'].items():
                    var.Start = float(init_fix['x'].get(key, 0))
                for key, var in mp_vars['alloc_boxes'].items():
                    var.Start = float(init_fix['alloc_boxes'].get(key, 0))
                for key, var in mp_vars['in_share'].items():
                    var.Start = float(init_fix['in_share'].get(key, 0))
                fixed_in_block_start = mp_vars.get('fixed_in_block', {})
                in_total_start = {}
                for k in K:
                    for n in N:
                        val = (
                            sum(
                                float(init_fix['in_share'].get((j, k, s, n), 0.0))
                                for j in J_new for s in G
                            )
                            + float(fixed_in_block_start.get((k, n), 0.0))
                        )
                        in_total_start[(k, n)] = val
                        mp_vars['in_total'][k, n].Start = val
                avg_start = {}
                for n in N:
                    avg = sum(in_total_start[(k, n)] for k in K) / float(len(K))
                    avg_start[n] = avg
                    mp_vars['avg_n'][n].Start = avg
                for k in K:
                    for n in N:
                        z = in_total_start[(k, n)] - avg_start[n]
                        mp_vars['g_bal'][k, n].Start = abs(z)
                for k in K:
                    for j in J_new:
                        for n in N:
                            bays = Bays_in_Block[k]
                            used = 1.0 if any(
                                float(init_fix['x'].get((i, j, n), 0)) > 0.5 for i in bays
                            ) or sum(
                                float(init_fix['in_share'].get((j, k, s, n), 0.0))
                                for s in G
                            ) > 1e-9 else 0.0
                            mp_vars['block_use_new'][k, j, n].Start = used
                # Check warm start quality with the same per-ship validator
                # used by callbacks.
                init_sp_total = 0.0
                for j in J_new:
                    sp_j, _sp_j_ctx = build_and_solve_sp_per_ship_lp(
                        data, init_fix, weights, j, verbose=False,
                    )
                    if sp_j.Status == GRB.OPTIMAL:
                        init_sp_total += float(sp_j.ObjVal)
                    else:
                        if verbose:
                            print(f"[BBC-v2-init] WARM-START SP_{j} status={sp_j.Status} "
                                  f"(start kept for Gurobi repair)")
                init_stats['init_sp_obj'] = init_sp_total
                init_stats['init_cuts'] = 0
                init_stats['warm_start_ok'] = True
                mp.update()
                if verbose:
                    print(f"[BBC-v2-init] warm-start loaded, init SP total = {init_sp_total:.2f}")
            except Exception as e:
                if verbose:
                    print(f"[BBC-v2-init] warm-start failed: {e}")

    # ---- Callback state ----
    state = {
        'user_cuts_added': 0,
        'node_benders_cuts_added': 0,
        'mipnode_calls': 0,
        'mipnode_budget_skips': 0,
        'mipnode_nonoptimal': 0,
        'mipnode_cache_hits': 0,
        'mipnode_no_cut': 0,
        'node_sp_solves': 0,
        'node_separations': 0,
        'sp_solves': 0,
        'sp_infeas': 0,
        'node_sp_infeas': 0,
        'feas_cuts_added': 0,
        'node_feas_cuts_added': 0,
        'best_ub': float('inf'),
        'best_pkg': None,
        'best_cb_bound': float('-inf'),
        'last_bound_improve_time': 0.0,
        'last_feas_cut_time': 0.0,
        'stop_reason': None,
        'time_in_callback': 0.0,
        'time_in_sp': 0.0,
    }
    if init_fix is not None:
        try:
            init_eval = _evaluate_mp_fix_v2(data, weights, init_fix)
        except Exception:
            init_eval = None
        if init_eval is not None:
            state['best_ub'] = float(init_eval['true_cost'])
            state['best_pkg'] = {
                'mp_fix': {
                    'x': dict(init_fix.get('x', {})),
                    'alloc_boxes': dict(init_fix.get('alloc_boxes', {})),
                    'in_share': dict(init_fix.get('in_share', {})),
                },
                'sp_obj_per_j': dict(init_eval.get('sp_obj_per_j', {})),
                'master_balance_l1': init_eval.get('real_l1'),
                'master_conflict': init_eval.get('obj_conflict'),
            }
    sp_cache: dict = {}
    node_cut_cache: set = set()

    def _pattern_key(mp_fix: dict) -> tuple:
        # Round x to int, alloc to int, in_share to 2-decimal for caching
        x_t = tuple(sorted((k, int(round(v))) for k, v in mp_fix['x'].items()))
        a_t = tuple(sorted((k, int(round(v))) for k, v in mp_fix['alloc_boxes'].items()))
        s_t = tuple(sorted((k, round(float(v), 2)) for k, v in mp_fix['in_share'].items()))
        return (x_t, a_t, s_t)

    def _node_pattern_key(mp_fix: dict) -> tuple:
        # Fractional node cuts are expensive; cache near-identical LP points.
        x_t = tuple(sorted((k, round(float(v), 3)) for k, v in mp_fix['x'].items()))
        a_t = tuple(sorted((k, round(float(v), 2)) for k, v in mp_fix['alloc_boxes'].items()))
        s_t = tuple(sorted((k, round(float(v), 2)) for k, v in mp_fix['in_share'].items()))
        return (x_t, a_t, s_t)

    def _update_bound_and_maybe_stop(model, bound_value) -> bool:
        try:
            bound = float(bound_value)
        except Exception:
            return False
        if bound > state['best_cb_bound'] + float(lb_improve_tol):
            state['best_cb_bound'] = bound
            state['last_bound_improve_time'] = time.perf_counter() - t_start

        elapsed = time.perf_counter() - t_start
        reported_gap = None
        if state['best_ub'] < float('inf'):
            reported_gap = (state['best_ub'] - bound) / max(abs(state['best_ub']), 1e-9)

        if reported_gap_stop is not None and reported_gap is not None:
            if elapsed >= float(min_runtime_s) and reported_gap <= float(reported_gap_stop):
                state['stop_reason'] = 'reported_gap'
                model.terminate()
                return True

        if lb_stall_time_s is not None and reported_gap is not None:
            stalled = elapsed - float(state['last_bound_improve_time'])
            gap_allows_stall = (
                lb_stall_gap_guard is None
                or reported_gap <= float(lb_stall_gap_guard)
            )
            if (
                gap_allows_stall
                and elapsed >= float(lb_stall_min_time_s)
                and stalled >= float(lb_stall_time_s)
            ):
                state['stop_reason'] = 'lb_stall'
                model.terminate()
                return True

        if feasibility_cut_stall_time_s is not None and state['best_ub'] < float('inf'):
            stalled = elapsed - float(state['last_feas_cut_time'])
            total_feas_cuts = (
                int(state.get('feas_cuts_added', 0))
                + int(state.get('node_feas_cuts_added', 0))
            )
            if (
                elapsed >= float(min_runtime_s)
                and total_feas_cuts > 0
                and stalled >= float(feasibility_cut_stall_time_s)
            ):
                state['stop_reason'] = 'feas_cut_stall'
                model.terminate()
                return True
        return False

    def callback(model, where):
        if where == GRB.Callback.MIPNODE:
            state['mipnode_calls'] += 1
            if not node_cuts_enabled:
                return
            if state['node_benders_cuts_added'] >= int(node_cut_limit):
                state['mipnode_budget_skips'] += 1
                return
            cb_t0 = time.perf_counter()
            try:
                try:
                    if _update_bound_and_maybe_stop(model, model.cbGet(GRB.Callback.MIPNODE_OBJBND)):
                        return
                except Exception:
                    pass
                if model.cbGet(GRB.Callback.MIPNODE_STATUS) != GRB.OPTIMAL:
                    state['mipnode_nonoptimal'] += 1
                    return
                mp_fix = _extract_mp_fix_v2(
                    mp_vars,
                    lambda v: model.cbGetNodeRel(v),
                )
                cache_key = _node_pattern_key(mp_fix)
                if cache_key in node_cut_cache:
                    state['mipnode_cache_hits'] += 1
                    return
                node_cut_cache.add(cache_key)
                state['node_separations'] += 1

                added_here = 0
                for j in J_new:
                    if state['node_benders_cuts_added'] >= int(node_cut_limit):
                        break
                    sp_t0 = time.perf_counter()
                    sp_j, sp_j_ctx = build_and_solve_sp_per_ship_lp(
                        data, mp_fix, weights, j, verbose=False,
                    )
                    state['time_in_sp'] += time.perf_counter() - sp_t0
                    state['node_sp_solves'] += 1
                    if sp_j.Status == GRB.OPTIMAL:
                        continue
                    state['node_sp_infeas'] += 1
                    try:
                        farkas_lin, rhs = _build_farkas_feasibility_cut_v2(
                            data, mp_vars, sp_j, sp_j_ctx,
                        )
                        lhs_val = _linexpr_value(
                            farkas_lin, lambda v: model.cbGetNodeRel(v)
                        )
                        if lhs_val < float(rhs) - cut_violation_tol:
                            model.cbCut(farkas_lin >= rhs)
                            state['node_benders_cuts_added'] += 1
                            state['node_feas_cuts_added'] += 1
                            state['last_feas_cut_time'] = time.perf_counter() - t_start
                            state['user_cuts_added'] += 1
                            added_here += 1
                    except Exception:
                        pass

                if added_here > 0 and verbose:
                    print(f"[BBC-v2-node] added {added_here} user cuts "
                          f"(total={state['user_cuts_added']})")
                if added_here == 0:
                    state['mipnode_no_cut'] += 1
            except Exception as e:
                if verbose:
                    print(f"[BBC-v2-node] user cut separation failed: {e}")
            finally:
                state['time_in_callback'] += time.perf_counter() - cb_t0
            return

        if where != GRB.Callback.MIPSOL:
            return
        cb_t0 = time.perf_counter()
        try:
            try:
                _update_bound_and_maybe_stop(model, model.cbGet(GRB.Callback.MIPSOL_OBJBND))
            except Exception:
                pass
            mp_fix = _extract_mp_fix_v2(
                mp_vars,
                lambda v: model.cbGetSolution(v),
            )
            cache_key = _pattern_key(mp_fix)
            cached = sp_cache.get(cache_key)
            if cached is not None:
                sp_obj_per_j = cached
            else:
                sp_obj_per_j = {}
                infeas = False
                feas_cuts_to_add = []  # list of (LinExpr, str) for failed SP_j
                for j in J_new:
                    sp_t0 = time.perf_counter()
                    sp_j, sp_j_ctx = build_and_solve_sp_per_ship_lp(
                        data, mp_fix, weights, j, verbose=False,
                    )
                    state['time_in_sp'] += time.perf_counter() - sp_t0
                    state['sp_solves'] += 1
                    if sp_j.Status != GRB.OPTIMAL:
                        infeas = True
                        # Build Farkas feasibility cut from sum(FarkasDual * RHS).
                        # For SP_j infeasible, FarkasDual on each constraint
                        # gives a certificate; the sum on RHS evaluated with
                        # The resulting MP expression must satisfy the certificate.
                        try:
                            farkas_lin = gp.LinExpr()
                            farkas_const = 0.0
                            # link_box_cap: RHS = alloc_boxes_fix
                            for (i, jj, s, n), c in sp_j_ctx['link_box_cap'].items():
                                fd = c.FarkasDual
                                if abs(fd) < 1e-9:
                                    continue
                                farkas_lin += fd * mp_vars['alloc_boxes'][i, jj, s, n]
                            # link_work: RHS = cap * dur * x_fix
                            for (i, jj, n), c in sp_j_ctx['link_work'].items():
                                fd = c.FarkasDual
                                if abs(fd) < 1e-9:
                                    continue
                                rem_cap = max(0.0, float(data['I'][i]['cap']) - float(_compute_old_occupancy(data).get((i, n), 0.0)))
                                cap_dur = rem_cap * float(data['Intervals'][n]['dur'])
                                farkas_lin += fd * (cap_dur * mp_vars['x'][i, jj, n])
                            # link_in_share: RHS = in_share_fix (per-size key)
                            for key, c in sp_j_ctx['link_in_share'].items():
                                fd = c.FarkasDual
                                if abs(fd) < 1e-9:
                                    continue
                                if len(key) == 4:
                                    jj, k, ss, nn = key
                                    farkas_lin += fd * mp_vars['in_share'][jj, k, ss, nn]
                                else:
                                    jj, k, nn = key
                                    for ss in _new_groups(data):
                                        farkas_lin += fd * mp_vars['in_share'][jj, k, ss, nn]
                            # arrivals: RHS = Arrivals (constant)
                            # inv balance: RHS = init or 0, mostly constant
                            # We capture remaining constants via SP constraints:
                            for c in sp_j.getConstrs():
                                fd_attr = getattr(c, 'FarkasDual', 0.0)
                                fd = float(fd_attr) if fd_attr is not None else 0.0
                                if abs(fd) < 1e-9:
                                    continue
                                cname = c.ConstrName
                                if cname.startswith("arr_") or cname.startswith("bal_"):
                                    farkas_const += fd * float(c.RHS)
                            # Cut: farkas_lin >= -farkas_const  (i.e. infeasible certificate)
                            feas_cuts_to_add.append((farkas_lin, -farkas_const, j))
                            if verbose:
                                print(f"[BBC-v2-CB] SP_{j} INFEAS, building Farkas feas cut")
                        except Exception as e:
                            # Fall back to no-good cut on (x, in_share) pattern
                            if verbose:
                                print(f"[BBC-v2-CB] Farkas cut failed for SP_{j}: {e}; using no-good")
                            ng_terms = []
                            for (i, jj, n), val in mp_fix['x'].items():
                                if jj != j:
                                    continue
                                bx = 1 if val >= 0.5 else 0
                                if bx > 0:
                                    ng_terms.append(1.0 - mp_vars['x'][i, jj, n])
                                else:
                                    ng_terms.append(mp_vars['x'][i, jj, n])
                            if ng_terms:
                                feas_cuts_to_add.append(("nogood", ng_terms, j))
                        break
                    sp_obj_j = float(sp_j.ObjVal)
                    sp_obj_per_j[j] = sp_obj_j
                if infeas:
                    state['sp_infeas'] += 1
                    # Apply feasibility cuts collected above
                    for cut_info in feas_cuts_to_add:
                        first = cut_info[0]
                        # Distinguish: tuple ("nogood", ng_terms, j) vs (LinExpr, rhs, j)
                        if isinstance(first, str) and first == "nogood":
                            _, ng_terms, _ = cut_info
                            try:
                                model.cbLazy(gp.quicksum(ng_terms) >= 1.0)
                                state['feas_cuts_added'] += 1
                                state['last_feas_cut_time'] = time.perf_counter() - t_start
                            except Exception as e:
                                if verbose:
                                    print(f"[BBC-v2-CB] no-good cbLazy failed: {e}")
                        else:
                            farkas_lin, rhs, _ = cut_info
                            terms_f = [
                                (farkas_lin.getCoeff(idx), farkas_lin.getVar(idx))
                                for idx in range(farkas_lin.size())
                            ]
                            expr = farkas_lin.getConstant()
                            for coeff, var in terms_f:
                                expr = expr + coeff * var
                            try:
                                model.cbLazy(expr >= rhs)
                                state['feas_cuts_added'] += 1
                                state['last_feas_cut_time'] = time.perf_counter() - t_start
                            except Exception as e:
                                if verbose:
                                    print(f"[BBC-v2-CB] cbLazy farkas failed: {e}")
                    sp_cache[cache_key] = None
                    return
                sp_cache[cache_key] = sp_obj_per_j

            # Master objective holds all core terms except the per-ship
            # realized distance computed by SP_j.
            in_total_v = {(k, n): float(model.cbGetSolution(mp_vars['in_total'][k, n]))
                          for k in K for n in N}
            raw_master = _master_raw_components_from_fix(data, mp_fix, in_total_v=in_total_v)
            sp_total = sum(sp_obj_per_j.values())
            ub_cand = _weighted_master_cost(data, weights, raw_master) + sp_total
            if ub_cand < state['best_ub'] - 1e-6:
                state['best_ub'] = ub_cand
                state['best_pkg'] = {
                    'mp_fix': dict(mp_fix),
                    'sp_obj_per_j': dict(sp_obj_per_j),
                    'master_balance_l1': raw_master.get('real_l1'),
                    'master_conflict': raw_master.get('obj_conflict'),
                }

            try:
                _update_bound_and_maybe_stop(model, model.cbGet(GRB.Callback.MIPSOL_OBJBND))
            except Exception:
                pass

        except Exception as e:
            import traceback
            print(f"[BBC-v2-CB] Exception: {e}")
            traceback.print_exc()
        finally:
            state['time_in_callback'] += time.perf_counter() - cb_t0

    t_start = time.perf_counter()
    mp.optimize(callback)
    t_total = time.perf_counter() - t_start

    status = mp.Status
    has_sol = mp.SolCount > 0
    try:
        mp_obj = float(mp.ObjVal) if has_sol else None
    except Exception:
        mp_obj = None
    lb = float(mp.ObjBound) if status in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED) else float('-inf')
    callback_ub = state['best_ub']
    final_eval = None
    if has_sol:
        try:
            final_fix = _extract_mp_fix_v2(mp_vars, lambda v: v.X)
            final_eval = _evaluate_mp_fix_v2(data, weights, final_fix)
            if (
                final_eval is not None
                and float(final_eval['true_cost']) < state['best_ub'] - 1e-6
            ):
                state['best_ub'] = float(final_eval['true_cost'])
                state['best_pkg'] = {
                    'mp_fix': final_fix,
                    'sp_obj_per_j': dict(final_eval.get('sp_obj_per_j', {})),
                    'master_balance_l1': final_eval.get('real_l1'),
                    'master_conflict': final_eval.get('obj_conflict'),
                }
                callback_ub = state['best_ub']
        except Exception:
            final_eval = None

    if has_sol:
        best_ub = callback_ub
    else:
        best_ub = callback_ub
    gap = (best_ub - lb) / max(abs(best_ub), 1e-9) if best_ub < float('inf') else float('inf')

    return {
        'ok': has_sol,
        'status': int(status),
        'mp_obj': mp_obj,
        'lb': lb,
        'best_ub': best_ub,
        'gap': gap,
        'balance_lb_mode': 'L1',
        'ub_balance_mode': 'L1',
        'user_cuts_added': state['user_cuts_added'],
        'node_benders_cuts_added': state.get('node_benders_cuts_added', 0),
        'mipnode_calls': state.get('mipnode_calls', 0),
        'mipnode_budget_skips': state.get('mipnode_budget_skips', 0),
        'mipnode_nonoptimal': state.get('mipnode_nonoptimal', 0),
        'mipnode_cache_hits': state.get('mipnode_cache_hits', 0),
        'mipnode_no_cut': state.get('mipnode_no_cut', 0),
        'sp_solves': state['sp_solves'],
        'node_sp_solves': state['node_sp_solves'],
        'node_separations': state['node_separations'],
        'sp_infeas': state['sp_infeas'],
        'node_sp_infeas': state.get('node_sp_infeas', 0),
        'feas_cuts_added': state.get('feas_cuts_added', 0),
        'node_feas_cuts_added': state.get('node_feas_cuts_added', 0),
        'stop_reason': state.get('stop_reason'),
        'best_cb_bound': state.get('best_cb_bound'),
        'time_total_s': t_total,
        'time_in_callback_s': state['time_in_callback'],
        'time_in_sp_s': state['time_in_sp'],
        'mp': mp,
        'mp_vars': mp_vars,
        'best_pkg': state['best_pkg'],
        'init_stats': init_stats,
    }


# =====================================================================
# V2 LNS / ALNS adapter: destroys x, lets master re-optimize in_share
# =====================================================================
def _evaluate_mp_fix_v2(data, weights, mp_fix):
    """
    Given a v2-style mp_fix (with x, alloc_boxes, in_share), solve all
    per-ship SP_j and compute the true total cost using exact L1 balance.

    Returns dict with keys: ok, true_cost, sp_total, real_l1, conflict,
    obj_x_val, sp_obj_per_j or None on infeasibility.
    """
    K = data['K']
    J_new = data['J_new']
    N = data['N']

    # Solve per-ship SPs
    sp_obj_per_j = {}
    for j in J_new:
        sp_j, sp_j_ctx = build_and_solve_sp_per_ship_lp(
            data, mp_fix, weights, j, verbose=False,
        )
        if sp_j.Status != GRB.OPTIMAL:
            return None
        sp_obj_per_j[j] = float(sp_j.ObjVal)
    sp_total = sum(sp_obj_per_j.values())

    # Compute in_total at this mp_fix to evaluate exact L1 balance and conflict.
    raw = _master_raw_components_from_fix(data, mp_fix)
    true_cost = _weighted_master_cost(data, weights, raw) + sp_total
    return {
        'ok': True,
        'true_cost': true_cost,
        'sp_total': sp_total,
        'sp_obj_per_j': sp_obj_per_j,
        'real_l1': raw['real_l1'],
        'obj_conflict': raw['obj_conflict'],
        'obj_x_val': raw['obj_x'],
        'pod_spread': raw.get('pod_spread', 0.0),
        'weight_spread': raw.get('weight_spread', 0.0),
        'height_mix': raw.get('height_mix', 0.0),
        'in_total': raw['in_total'],
    }


def _set_lifted_master_start_from_fix(data: dict, mp_vars: dict, mp_fix: dict) -> None:
    K = data['K']
    I_list = data['I_list']
    J_new = data['J_new']
    J_old = data['J_old']
    S = data['S']
    G = _new_groups(data)
    N = data['N']
    Bays_in_Block = data['Bays_in_Block']
    Fixed_In_Flow = data['Fixed_In_Flow']

    for key, var in mp_vars.get('x', {}).items():
        var.Start = float(mp_fix.get('x', {}).get(key, 0.0))
    for key, var in mp_vars.get('alloc_boxes', {}).items():
        var.Start = float(mp_fix.get('alloc_boxes', {}).get(key, 0.0))
    for key, var in mp_vars.get('in_share', {}).items():
        var.Start = float(mp_fix.get('in_share', {}).get(key, 0.0))

    if 'block_use_new' in mp_vars:
        for k in K:
            bays = Bays_in_Block[k]
            for j in J_new:
                for n in N:
                    used = 1.0 if any(
                        float(mp_fix.get('x', {}).get((i, j, n), 0.0)) > 0.5
                        for i in bays
                    ) else 0.0
                    mp_vars['block_use_new'][k, j, n].Start = used

    if 'in_total' in mp_vars and 'avg_n' in mp_vars and 'g_bal' in mp_vars:
        fixed_in_block = {(k, n): 0.0 for k in K for n in N}
        for k in K:
            bays = Bays_in_Block[k]
            for n in N:
                fixed_in_block[(k, n)] = sum(
                    float(Fixed_In_Flow[(j, s, i, n)])
                    for i in bays for j in J_old for s in S
                )
        in_total_start = {}
        for k in K:
            for n in N:
                new_in = sum(
                    float(mp_fix.get('in_share', {}).get((j, k, s, n), 0.0))
                    for j in J_new for s in G
                )
                val = new_in + fixed_in_block[(k, n)]
                in_total_start[(k, n)] = val
                mp_vars['in_total'][k, n].Start = val
        for n in N:
            avg = sum(in_total_start[(k, n)] for k in K) / float(len(K))
            mp_vars['avg_n'][n].Start = avg
            for k in K:
                z = in_total_start[(k, n)] - avg
                mp_vars['g_bal'][k, n].Start = abs(z)

    final_n = max(N) if N else 0
    if mp_vars.get('pod_block_use'):
        pod_values = _attribute_values(data, "pod")
        for j in J_new:
            for pod in pod_values:
                for k in K:
                    used = 1.0 if sum(
                        float(mp_fix.get('alloc_boxes', {}).get((i, j, g, final_n), 0.0))
                        for i in Bays_in_Block[k]
                        for g in G
                        if _group_attr(data, g, "pod") == pod
                    ) > 1e-6 else 0.0
                    mp_vars['pod_block_use'][j, pod, k].Start = used

    if mp_vars.get('weight_block_use'):
        weight_values = _attribute_values(data, "weight_class")
        for j in J_new:
            for weight_class in weight_values:
                for k in K:
                    used = 1.0 if sum(
                        float(mp_fix.get('alloc_boxes', {}).get((i, j, g, final_n), 0.0))
                        for i in Bays_in_Block[k]
                        for g in G
                        if _group_attr(data, g, "weight_class") == weight_class
                    ) > 1e-6 else 0.0
                    mp_vars['weight_block_use'][j, weight_class, k].Start = used

    if mp_vars.get('bay_height_used') and mp_vars.get('bay_height_mix'):
        height_values = _attribute_values(data, "height")
        for i in I_list:
            for n in N:
                used_heights = set()
                for height in height_values:
                    used = 0.0
                    for j in J_new:
                        for g in G:
                            if _group_attr(data, g, "height") != height:
                                continue
                            if float(mp_fix.get('alloc_boxes', {}).get((i, j, g, n), 0.0)) > 1e-6:
                                used = 1.0
                                used_heights.add(height)
                                break
                        if used > 0.5:
                            break
                    mp_vars['bay_height_used'][i, height, n].Start = used
                mp_vars['bay_height_mix'][i, n].Start = max(0.0, float(len(used_heights) - 1))


def _attribute_polish_objective(data: dict, weights: Weights, mp_vars: dict):
    scales = _objective_scales(data)
    attr = _attribute_polish_weights(weights)
    obj_pod = gp.quicksum(v for v in mp_vars.get('pod_block_use', {}).values())
    obj_weight = gp.quicksum(v for v in mp_vars.get('weight_block_use', {}).values())
    obj_height = gp.quicksum(v for v in mp_vars.get('bay_height_mix', {}).values())
    expr = (
        float(getattr(attr, "pod_spread", 0.0)) * obj_pod / scales["pod_spread"]
        + float(getattr(attr, "weight_spread", 0.0)) * obj_weight / scales["weight_spread"]
        + float(getattr(attr, "height_mix", 0.0)) * obj_height / scales["height_mix"]
    )
    return _objective_scale_factor(weights) * expr


def _attribute_polish_v2(
    data: dict,
    weights: Weights,
    initial_mp_fix: dict,
    *,
    core_ub: float,
    core_tolerance: float = 0.01,
    time_limit_s: float = 20.0,
    mip_gap: float = 0.03,
    gurobi_params: dict | None = None,
    verbose: bool = True,
) -> dict:
    """
    Improve pod/weight/height layout after the provable core solve.

    The core objective is constrained within a small degradation band, and the
    resulting attribute score is reported separately.  This phase never updates
    the reported core UB/LB gap.
    """
    t0 = time.perf_counter()
    start_eval = _evaluate_mp_fix_v2(data, weights, initial_mp_fix) if initial_mp_fix else None
    if start_eval is None:
        return {
            'ok': False,
            'accepted': False,
            'status': None,
            'reason': 'initial_solution_infeasible',
            'time_total_s': time.perf_counter() - t0,
        }

    start_raw = _master_raw_components_from_fix(data, initial_mp_fix)
    start_score = _attribute_score(data, weights, start_raw)
    start_core = float(start_eval['true_cost'])
    core_cap = max(float(core_ub), start_core) * (1.0 + max(0.0, float(core_tolerance)))

    model, mp_vars = build_master_v2(
        data,
        weights,
        include_attribute_helpers=True,
    )
    _set_lifted_master_start_from_fix(data, mp_vars, initial_mp_fix)
    core_objective = model.getObjective()
    model.addConstr(core_objective <= core_cap + 1e-6, name="attribute_polish_core_cap")
    model.setObjective(_attribute_polish_objective(data, weights, mp_vars), GRB.MINIMIZE)

    params = {
        "MIPFocus": 1,
        "Cuts": 1,
        "Presolve": 2,
        "Heuristics": 0.20,
    }
    if gurobi_params:
        params.update(gurobi_params)
    model.Params.OutputFlag = 1 if verbose else 0
    model.Params.TimeLimit = float(time_limit_s)
    model.Params.MIPGap = float(mip_gap)
    for param_name, param_value in params.items():
        try:
            model.setParam(str(param_name), param_value)
        except Exception:
            if verbose:
                print(f"[Attribute-polish] ignored invalid Gurobi parameter {param_name}={param_value}")

    model.optimize()
    wall = time.perf_counter() - t0
    has_sol = model.SolCount > 0
    result = {
        'ok': bool(has_sol),
        'accepted': False,
        'status': int(model.Status),
        'time_total_s': wall,
        'sol_count': int(model.SolCount),
        'node_count': float(model.NodeCount),
        'start_core_cost': start_core,
        'core_cap': core_cap,
        'core_tolerance': float(core_tolerance),
        'start_attribute_score': start_score,
        'start_components': {
            'pod_spread': start_raw.get('pod_spread', 0.0),
            'weight_spread': start_raw.get('weight_spread', 0.0),
            'height_mix': start_raw.get('height_mix', 0.0),
        },
        'candidate_core_cost': None,
        'candidate_attribute_score': None,
        'candidate_components': None,
        'candidate_feasible': False,
        'core_degradation_vs_start': None,
        'best_pkg': {'mp_fix': initial_mp_fix},
    }
    if model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.INTERRUPTED, GRB.SUBOPTIMAL):
        try:
            result['model_bound'] = float(model.ObjBound)
        except Exception:
            result['model_bound'] = None
        if has_sol:
            try:
                result['model_obj'] = float(model.ObjVal)
                result['model_gap'] = float(model.MIPGap)
            except Exception:
                pass
    if not has_sol:
        return result

    mp_fix = {
        'x': {k: float(v.X) for k, v in mp_vars['x'].items()},
        'alloc_boxes': {k: float(v.X) for k, v in mp_vars['alloc_boxes'].items()},
        'in_share': {k: float(v.X) for k, v in mp_vars['in_share'].items()},
    }
    eval_res = _evaluate_mp_fix_v2(data, weights, mp_fix)
    if eval_res is None:
        return result

    result['candidate_feasible'] = True
    candidate_core = float(eval_res['true_cost'])
    raw = _master_raw_components_from_fix(data, mp_fix)
    candidate_score = _attribute_score(data, weights, raw)
    result['candidate_core_cost'] = candidate_core
    result['candidate_attribute_score'] = candidate_score
    result['candidate_components'] = {
        'pod_spread': raw.get('pod_spread', 0.0),
        'weight_spread': raw.get('weight_spread', 0.0),
        'height_mix': raw.get('height_mix', 0.0),
    }
    result['core_degradation_vs_start'] = (
        (candidate_core - start_core) / max(abs(start_core), 1e-9)
    )

    if candidate_core <= core_cap + 1e-5 and candidate_score < start_score - 1e-6:
        result['accepted'] = True
        result['best_pkg'] = {'mp_fix': mp_fix}
    return result


def adaptive_lns_polish_v2(
    data: dict,
    weights: Weights,
    initial_mp_fix: dict,
    *,
    time_limit_s: float | None = None,
    sub_mip_time: float = 18.0,
    n_iterations: int | None = 25,
    destroy_fractions: tuple = (0.10, 0.20, 0.35),
    enabled_operators: tuple = ("random", "active", "block", "interval", "ship", "conflict", "distance"),
    use_sa: bool = True,
    initial_temperature: float = 0.012,
    cooling_rate: float = 0.92,
    restart_after_no_improve: int = 4,
    early_stop_no_improve_iters: int | None = 8,
    early_stop_min_iters: int = 6,
    early_stop_min_time_s: float = 30.0,
    adaptive_destroy_on_stall: bool = True,
    score_improve: float = 4.0,
    score_accept_worse: float = 1.5,
    score_reject: float = 0.0,
    weight_decay: float = 0.85,
    seed: int = 42,
    verbose: bool = True,
):
    """
    Adaptive LNS for V2 master. Each iter:
      1. Pick destroy operator + fraction.
      2. Destroy a subset of x[i,j,n].
      3. Build a SUB v2 master: freeze non-destroyed x; freeze non-destroyed
         alloc; let in_share & destroyed-x re-optimize.
      4. Solve sub-MIP (with v2 lazy callback for per-ship multi-cut).
      5. Evaluate TRUE cost via _evaluate_mp_fix_v2; SA-accept or improve.
    """
    rng = random.Random(seed)
    K = data['K']
    J_new = data['J_new']
    N = data['N']
    S = data['S']
    Bays_in_Block = data['Bays_in_Block']
    Intervals = data['Intervals']

    t_start = time.perf_counter()
    cur = _evaluate_mp_fix_v2(data, weights, initial_mp_fix)
    if cur is None:
        return {'best_mp_fix': None, 'best_ub': float('inf'), 'history': [],
                'time_total_s': 0.0, 'op_stats': {}, 'sa_accepts': 0}

    best_fix = {
        'x': dict(initial_mp_fix['x']),
        'alloc_boxes': dict(initial_mp_fix['alloc_boxes']),
        'in_share': dict(initial_mp_fix['in_share']),
    }
    best_ub = cur['true_cost']
    current_fix = {k: dict(v) if isinstance(v, dict) else v for k, v in best_fix.items()}
    current_ub = best_ub

    op_weights = {op: 1.0 for op in enabled_operators}
    if "active" in op_weights:
        op_weights["active"] = 2.5
    if "conflict" in op_weights:
        op_weights["conflict"] = 2.0
    if "distance" in op_weights:
        op_weights["distance"] = 1.5
    op_stats = {op: {'used': 0, 'improved': 0, 'accepted': 0, 'rejected': 0}
                for op in enabled_operators}
    sa_accepts = 0
    no_improve_streak = 0
    best_no_improve_iters = 0
    stop_reason = "iteration_limit"
    temperature = initial_temperature
    history = [{'iter': 0, 'best_ub': best_ub, 'op': None}]
    iters_attempted = 0

    if verbose:
        print(f"[ALNS-v2] start UB = {best_ub:.2f} (sp_dist={cur['sp_total']:.2f}, "
              f"L1={cur['real_l1']:.2f}); ops={list(enabled_operators)}", flush=True)

    it = 0
    while True:
        it += 1
        if n_iterations is not None and it > int(n_iterations):
            break
        iters_attempted = it
        elapsed = time.perf_counter() - t_start
        if time_limit_s is not None and elapsed >= float(time_limit_s):
            if verbose:
                print(f"[ALNS-v2] time limit at iter {it}", flush=True)
            stop_reason = "time_limit"
            break

        op_chosen = _select_operator(rng, op_weights)
        destroy_pool = list(destroy_fractions)
        if adaptive_destroy_on_stall and best_no_improve_iters >= max(2, restart_after_no_improve // 2):
            destroy_pool = sorted(set(destroy_pool + [0.55]))
        destroy_frac = rng.choice(destroy_pool)
        n_destroy = max(1, int(destroy_frac * len(current_fix['x'])))

        if op_chosen == "random":
            destroyed = _destroy_random(rng, current_fix['x'], n_destroy)
        elif op_chosen == "active":
            destroyed = _destroy_active_biased(rng, current_fix['x'], n_destroy)
        elif op_chosen == "block":
            destroyed = _destroy_block_focused(rng, data, current_fix['x'], n_destroy)
        elif op_chosen == "interval":
            destroyed = _destroy_interval_focused(rng, data, current_fix['x'], n_destroy)
        elif op_chosen == "ship":
            destroyed = _destroy_ship_focused(rng, data, current_fix['x'], n_destroy)
        elif op_chosen == "conflict":
            destroyed = _destroy_conflict_focused(rng, data, current_fix['x'], n_destroy)
        elif op_chosen == "distance":
            destroyed = _destroy_distance_focused(rng, data, current_fix['x'], n_destroy)
        else:
            destroyed = _destroy_random(rng, current_fix['x'], n_destroy)

        op_stats[op_chosen]['used'] += 1
        actual_n = len(destroyed)

        # Build sub-master v2 with frozen non-destroyed x
        sub, sub_vars = build_master_v2(
            data, weights,
        )
        sub.Params.OutputFlag = 0
        sub.Params.TimeLimit = sub_mip_time
        sub.Params.MIPGap = 0.02
        sub.Params.LazyConstraints = 1
        sub.Params.MIPFocus = 1
        sub.Params.Presolve = 2

        for key, val in current_fix['x'].items():
            v = sub_vars['x'][key]
            if key not in destroyed:
                fv = 1.0 if val > 0.5 else 0.0
                v.LB = fv
                v.UB = fv

        # alloc_boxes is cumulative/nondecreasing in n.  Releasing only the
        # destroyed interval leaves it pinned by frozen predecessor/successor
        # values, so release the full time axis for every affected bay-ship.
        affected_bay_ship = {(i, j) for (i, j, _n) in destroyed}
        released_alloc = set()
        for (i, j, s, n) in current_fix['alloc_boxes'].keys():
            if (i, j) in affected_bay_ship:
                released_alloc.add((i, j, s, n))

        for key, val in current_fix['alloc_boxes'].items():
            if key not in released_alloc:
                v = sub_vars['alloc_boxes'][key]
                rv = float(int(round(val)))
                v.LB = rv
                v.UB = rv

        # Inject a complete current incumbent start, including lifted soft
        # variables added by the attribute-aware model.
        _set_lifted_master_start_from_fix(data, sub_vars, current_fix)
        sub.update()

        sub_state = {'cuts': 0, 'feas_cuts': 0, 'sps': 0}
        sub_sp_cache = {}

        def _sub_pkey(mfx):
            return (
                tuple(sorted((k, int(round(v))) for k, v in mfx['x'].items())),
                tuple(sorted((k, int(round(v))) for k, v in mfx['alloc_boxes'].items())),
                tuple(sorted((k, round(float(v), 2)) for k, v in mfx['in_share'].items())),
            )

        def sub_callback(model, where):
            if where != GRB.Callback.MIPSOL:
                return
            try:
                xv = model.cbGetSolution(sub_vars['x'])
                av = model.cbGetSolution(sub_vars['alloc_boxes'])
                isv = model.cbGetSolution(sub_vars['in_share'])
                mfx = {
                    'x': {k: float(v) for k, v in xv.items()},
                    'alloc_boxes': {k: float(v) for k, v in av.items()},
                    'in_share': {k: float(v) for k, v in isv.items()},
                }
                pkey = _sub_pkey(mfx)
                if pkey in sub_sp_cache:
                    return
                infeas = False
                for j in J_new:
                    sp_jj, sp_jj_ctx = build_and_solve_sp_per_ship_lp(
                        data, mfx, weights, j, verbose=False,
                    )
                    sub_state['sps'] += 1
                    if sp_jj.Status != GRB.OPTIMAL:
                        infeas = True
                        try:
                            fcut, rhs = _build_farkas_feasibility_cut_v2(
                                data, sub_vars, sp_jj, sp_jj_ctx,
                            )
                            model.cbLazy(fcut >= rhs)
                            sub_state['feas_cuts'] += 1
                            sub_state['cuts'] += 1
                        except Exception:
                            ng_terms = []
                            for (i, jj, n), val in mfx['x'].items():
                                if jj != j:
                                    continue
                                bx = 1 if val >= 0.5 else 0
                                ng_terms.append((1.0 - sub_vars['x'][i, jj, n]) if bx else sub_vars['x'][i, jj, n])
                        if ng_terms:
                            model.cbLazy(gp.quicksum(ng_terms) >= 1.0)
                            sub_state['feas_cuts'] += 1
                            sub_state['cuts'] += 1
                        break
                if infeas:
                    sub_sp_cache[pkey] = False
                    return
                sub_sp_cache[pkey] = True
                # L1 balance is already exact in the lifted master; the sub-MIP
                # only separates per-ship feasibility cuts when an incumbent
                # pattern cannot be realized at bay level.
            except Exception:
                pass

        try:
            sub.optimize(sub_callback)
        except Exception:
            op_stats[op_chosen]['rejected'] += 1
            no_improve_streak += 1
            best_no_improve_iters += 1
            if verbose:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} optimize failed", flush=True)
            continue

        if sub.SolCount == 0:
            op_stats[op_chosen]['rejected'] += 1
            no_improve_streak += 1
            best_no_improve_iters += 1
            if verbose:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} no repair incumbent", flush=True)
            continue

        new_fix = {
            'x': {k: float(v.X) for k, v in sub_vars['x'].items()},
            'alloc_boxes': {k: float(v.X) for k, v in sub_vars['alloc_boxes'].items()},
            'in_share': {k: float(v.X) for k, v in sub_vars['in_share'].items()},
        }
        eval_res = _evaluate_mp_fix_v2(data, weights, new_fix)
        if eval_res is None:
            op_stats[op_chosen]['rejected'] += 1
            no_improve_streak += 1
            best_no_improve_iters += 1
            if verbose:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} infeasible after evaluation", flush=True)
            continue
        cand_ub = eval_res['true_cost']
        improved_best = cand_ub < best_ub - 1e-3
        improved_current = cand_ub < current_ub - 1e-3
        delta = cand_ub - current_ub
        accept = improved_current
        sa_accept = False
        if not accept and use_sa and delta > 0:
            if temperature > 1e-9:
                p = math.exp(-delta / max(abs(current_ub), 1e-9) / temperature)
                if rng.random() < p:
                    accept = True
                    sa_accept = True
                    sa_accepts += 1

        if improved_best:
            improvement_pct = (best_ub - cand_ub) / max(abs(best_ub), 1e-9)
            best_ub = cand_ub
            best_fix = {
                'x': dict(new_fix['x']),
                'alloc_boxes': dict(new_fix['alloc_boxes']),
                'in_share': dict(new_fix['in_share']),
            }
            current_fix = {k: dict(v) if isinstance(v, dict) else v for k, v in best_fix.items()}
            current_ub = best_ub
            no_improve_streak = 0
            best_no_improve_iters = 0
            op_stats[op_chosen]['improved'] += 1
            op_stats[op_chosen]['accepted'] += 1
            op_weights[op_chosen] = op_weights[op_chosen] * weight_decay + score_improve
            if verbose:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} "
                      f"BEST UB: {cand_ub:.2f} ({-improvement_pct:+.3%}) "
                      f"sub_cuts={sub_state['cuts']} sub_sps={sub_state['sps']}", flush=True)
        elif accept:
            current_ub = cand_ub
            current_fix = {k: dict(v) if isinstance(v, dict) else v for k, v in new_fix.items()}
            no_improve_streak += 1
            best_no_improve_iters += 1
            op_stats[op_chosen]['accepted'] += 1
            op_weights[op_chosen] = op_weights[op_chosen] * weight_decay + score_accept_worse
            if verbose and sa_accept:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} "
                      f"SA-accept worse: {current_ub:.2f} (delta={delta:+.2f})", flush=True)
        else:
            no_improve_streak += 1
            best_no_improve_iters += 1
            op_stats[op_chosen]['rejected'] += 1
            op_weights[op_chosen] = op_weights[op_chosen] * weight_decay + score_reject
            if verbose:
                print(f"[ALNS-v2 iter {it}] {op_chosen:8s} d={destroy_frac:.2f} "
                      f"reject (cand={cand_ub:.2f}, best={best_ub:.2f})", flush=True)

        history.append({
            'iter': it, 'op': op_chosen, 'destroy_frac': destroy_frac,
            'best_ub': best_ub, 'current_ub': current_ub,
            'cand_ub': cand_ub, 'sub_cuts': sub_state['cuts'],
        })

        elapsed = time.perf_counter() - t_start
        if (
            early_stop_no_improve_iters is not None
            and best_no_improve_iters >= int(early_stop_no_improve_iters)
            and it >= int(early_stop_min_iters)
            and elapsed >= float(early_stop_min_time_s)
        ):
            stop_reason = "no_best_improvement"
            if verbose:
                print(
                    f"[ALNS-v2] adaptive stop: no best UB improvement for "
                    f"{best_no_improve_iters} iterations "
                    f"(elapsed={elapsed:.1f}s, best={best_ub:.2f})",
                    flush=True,
                )
            break

        if no_improve_streak >= restart_after_no_improve:
            if verbose:
                print(f"[ALNS-v2 iter {it}] restart from best UB={best_ub:.2f}", flush=True)
            current_fix = {k: dict(v) if isinstance(v, dict) else v for k, v in best_fix.items()}
            current_ub = best_ub
            no_improve_streak = 0

        temperature = max(0.001, temperature * cooling_rate)

    return {
        'best_mp_fix': best_fix,
        'best_ub': best_ub,
        'history': history,
        'iters_attempted': iters_attempted,
        'time_total_s': time.perf_counter() - t_start,
        'stop_reason': stop_reason,
        'best_no_improve_iters': best_no_improve_iters,
        'op_stats': op_stats,
        'sa_accepts': sa_accepts,
        'op_weights_final': dict(op_weights),
    }


# =====================================================================
# Pipeline v2: BBC v2 -> ALNS v2 -> BBC v2 restart
# =====================================================================
def solve_pipeline_v2(
    data: dict,
    weights: Weights,
    *,
    bbc_phase1_time_s: float | None = 20.0,
    lns_time_s: float | None = 45.0,
    lns_iters: int | None = 25,
    lns_sub_mip_time: float = 16.0,
    bbc_phase3_time_s: float | None = 20.0,
    use_alns: bool = True,
    use_node_cuts: bool = True,
    node_cut_limit: int = 250,
    phase3_node_cut_multiplier: float = 2.0,
    adaptive_lns_time: bool = True,
    lns_early_stop_no_improve_iters: int | None = 8,
    lns_early_stop_min_iters: int = 1,
    lns_early_stop_min_time_s: float = 15.0,
    lns_restarts: int = 1,
    lns_seed_base: int = 42,
    attribute_polish_time_s: float | None = 20.0,
    attribute_polish_core_tolerance: float = 0.01,
    attribute_polish_mip_gap: float = 0.03,
    attribute_polish_gurobi_params: dict | None = None,
    bbc_phase1_min_time_s: float = 10.0,
    bbc_phase1_feas_cut_stall_time_s: float | None = 5.0,
    bbc_phase3_reported_gap_stop: float | None = 0.03,
    bbc_phase3_lb_stall_time_s: float | None = 6.0,
    bbc_phase3_lb_stall_min_time_s: float = 0.0,
    bbc_phase3_lb_stall_gap_guard: float | None = None,
    verbose: bool = True,
):
    """
    Three-phase pipeline using v2 architecture (per-ship SP + lifted master).
    """
    out = {
        'phase1': None,
        'lns': None,
        'phase3': None,
        'attribute_polish': None,
        'best_ub': float('inf'),
        'best_mp_fix': None,
        'final_mp_fix': None,
    }

    def _budget_label(seconds):
        return "adaptive" if seconds is None else f"{float(seconds):.1f}s"

    if verbose:
        print(f"\n{'=' * 60}\n[Pipeline v2] Phase 1: BBC v2 for {_budget_label(bbc_phase1_time_s)}\n{'=' * 60}", flush=True)
    p1 = solve_benders_bbc_v2(
        data, weights,
        time_limit_s=bbc_phase1_time_s,
        mip_gap=0.05,
        verbose=False,
        use_node_cuts=use_node_cuts,
        node_cut_limit=node_cut_limit,
        min_runtime_s=bbc_phase1_min_time_s,
        feasibility_cut_stall_time_s=bbc_phase1_feas_cut_stall_time_s,
    )
    out['phase1'] = p1
    if verbose:
        print(f"[Pipeline v2] Phase 1 done: LB={p1['lb']:.2f} UB={p1['best_ub']:.2f} "
              f"feas_cuts={p1['feas_cuts_added']} sp={p1['sp_solves']}", flush=True)

    if p1['best_pkg'] is None:
        if verbose:
            print("[Pipeline v2] Phase 1 found no incumbent; aborting", flush=True)
        return out

    out['best_ub'] = p1['best_ub']
    out['best_mp_fix'] = p1['best_pkg']['mp_fix']
    out['final_mp_fix'] = out['best_mp_fix']

    if not use_alns:
        return out

    if verbose:
        print(f"\n{'=' * 60}\n[Pipeline v2] Phase 2: ALNS v2 for {_budget_label(lns_time_s)}\n{'=' * 60}", flush=True)
    lns_ops = ("random", "active", "block", "interval", "ship", "conflict", "distance")
    phase2_start_fix = p1['best_pkg']['mp_fix']
    lns_runs = []
    n_lns_restarts = max(1, int(lns_restarts))
    for r in range(n_lns_restarts):
        if verbose and n_lns_restarts > 1:
            print(f"[Pipeline v2] ALNS restart {r + 1}/{n_lns_restarts}", flush=True)
        lns_run = adaptive_lns_polish_v2(
            data, weights, phase2_start_fix,
            time_limit_s=lns_time_s,
            n_iterations=lns_iters,
            sub_mip_time=lns_sub_mip_time,
            enabled_operators=lns_ops,
            # Aggressive destroy fractions: very small for fine-tuning,
            # very large for breaking out of local optima
            destroy_fractions=(0.05, 0.12, 0.22, 0.40),
            initial_temperature=0.020,    # warmer SA for more accept-worse
            cooling_rate=0.95,
            restart_after_no_improve=5,
            early_stop_no_improve_iters=lns_early_stop_no_improve_iters if adaptive_lns_time else None,
            early_stop_min_iters=lns_early_stop_min_iters,
            early_stop_min_time_s=lns_early_stop_min_time_s,
            seed=int(lns_seed_base) + 997 * r,
            verbose=verbose,
        )
        lns_run['restart_index'] = r
        lns_run['seed'] = int(lns_seed_base) + 997 * r
        lns_runs.append(lns_run)

    lns_res = min(lns_runs, key=lambda rr: float(rr.get('best_ub', float('inf'))))
    if n_lns_restarts > 1:
        lns_res = dict(lns_res)
        lns_res['restarts'] = [
            {
                'restart_index': rr.get('restart_index'),
                'seed': rr.get('seed'),
                'best_ub': rr.get('best_ub'),
                'time_total_s': rr.get('time_total_s'),
                'iters_attempted': rr.get('iters_attempted'),
                'stop_reason': rr.get('stop_reason'),
            }
            for rr in lns_runs
        ]
        lns_res['time_total_s'] = sum(float(rr.get('time_total_s', 0.0) or 0.0) for rr in lns_runs)
        lns_res['iters_attempted'] = sum(int(rr.get('iters_attempted', 0) or 0) for rr in lns_runs)
        lns_res['stop_reason'] = f"multi_restart_best_seed_{lns_res.get('seed')}"

    out['lns'] = lns_res
    if lns_res['best_ub'] < out['best_ub']:
        out['best_ub'] = lns_res['best_ub']
        out['best_mp_fix'] = lns_res['best_mp_fix']
        if verbose:
            print(f"[Pipeline v2] Phase 2 improved: UB={out['best_ub']:.2f}", flush=True)

    # Phase 3: proof-oriented BBC restart with the best incumbent as warm start.
    phase3_time_s = None if bbc_phase3_time_s is None else float(bbc_phase3_time_s)
    if verbose:
        print(f"\n{'=' * 60}\n[Pipeline v2] Phase 3: BBC v2 proof/LB for {_budget_label(phase3_time_s)} (exact L1 balance)\n{'=' * 60}", flush=True)
    p3 = solve_benders_bbc_v2(
        data, weights,
        time_limit_s=phase3_time_s,
        mip_gap=0.01,
        verbose=False,
        initial_mp_fix=out['best_mp_fix'],
        use_node_cuts=use_node_cuts,
        node_cut_limit=max(int(node_cut_limit), int(round(node_cut_limit * phase3_node_cut_multiplier))),
        reported_gap_stop=bbc_phase3_reported_gap_stop,
        min_runtime_s=bbc_phase3_lb_stall_min_time_s,
        lb_stall_time_s=bbc_phase3_lb_stall_time_s,
        lb_stall_min_time_s=bbc_phase3_lb_stall_min_time_s,
        lb_stall_gap_guard=bbc_phase3_lb_stall_gap_guard,
        gurobi_params={
            "MIPFocus": 3,
            "Cuts": 2,
            "Presolve": 2,
            "Heuristics": 0.02,
        },
    )
    out['phase3'] = p3
    if p3['best_ub'] < out['best_ub']:
        out['best_ub'] = p3['best_ub']
        out['best_mp_fix'] = p3['best_pkg']['mp_fix'] if p3['best_pkg'] else out['best_mp_fix']
        if verbose:
            print(f"[Pipeline v2] Phase 3 improved: UB={out['best_ub']:.2f}", flush=True)
    out['final_mp_fix'] = out['best_mp_fix']

    if attribute_polish_time_s is not None and float(attribute_polish_time_s) > 1e-9:
        if verbose:
            print(f"\n{'=' * 60}\n[Pipeline v2] Attribute polish for {_budget_label(attribute_polish_time_s)} "
                  f"(core tolerance {100.0 * float(attribute_polish_core_tolerance):.2f}%)\n{'=' * 60}", flush=True)
        attr_res = _attribute_polish_v2(
            data,
            weights,
            out['best_mp_fix'],
            core_ub=float(out['best_ub']),
            core_tolerance=float(attribute_polish_core_tolerance),
            time_limit_s=float(attribute_polish_time_s),
            mip_gap=float(attribute_polish_mip_gap),
            gurobi_params=attribute_polish_gurobi_params,
            verbose=verbose,
        )
        out['attribute_polish'] = attr_res
        if attr_res.get('accepted') and attr_res.get('best_pkg'):
            out['final_mp_fix'] = attr_res['best_pkg']['mp_fix']
            if verbose:
                print(
                    f"[Pipeline v2] Attribute polish accepted: "
                    f"score {attr_res.get('start_attribute_score'):.2f} -> "
                    f"{attr_res.get('candidate_attribute_score'):.2f}; "
                    f"core={attr_res.get('candidate_core_cost'):.2f}",
                    flush=True,
                )

    return out


if __name__ == "__main__":
    # Convenience entry; `python -u main.py` is the recommended way to run.
    from data import get_data_3new6old_fixed
    pipe = solve_pipeline_v2(
        get_data_3new6old_fixed(), Weights(),
        verbose=True,
    )
    print()
    print(f"Final UB: {pipe['best_ub']:.2f}")

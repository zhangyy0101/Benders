"""Six-hour stability-aware rolling bay-slot allocation MIP."""
from __future__ import annotations

import gurobipy as gp
from gurobipy import GRB

from config import (
    OPERATION_WEIGHT_BALANCE,
    OPERATION_WEIGHT_CONCENTRATION,
    OPERATION_WEIGHT_DISTANCE,
    OPERATION_WEIGHT_IN_OUT_CONFLICT,
    STABILITY_BLOCK_REALLOCATION_WEIGHT,
    STABILITY_CANCEL_WEIGHT,
    STABILITY_NEW_BAY_WEIGHT,
    USE_NORMALIZED_OPERATION_OBJECTIVE,
)

INF = 10**9


def compatible(d: dict, bay: str, group: str) -> bool:
    return d["bay_size"][bay] == d["group_attrs"][group]["size"]


def ship_present_at(d: dict, ship: str, period: int) -> bool:
    """A planned ship occupies capacity strictly before whole-ship release."""
    return d["ship_release_local"].get(ship, INF) > period


def _old_block_amount(d: dict, ship: str, group: str, block: str) -> int:
    return sum(
        q
        for (bay, j, g), q in d["previous_reservation"].items()
        if j == ship and g == group and d["bay_block"][bay] == block
    )


def build_rolling_model(
    d: dict,
    *,
    allowed_bays: dict | None = None,
    shortage_allowed: bool = True,
    stability_budget: float | None = None,
) -> tuple[gp.Model, dict, dict]:
    m = gp.Model("rolling_6h_bay_allocation")
    m.Params.OutputFlag = 0
    bays, periods, attrs = d["bays"], d["periods"], d["group_attrs"]
    pairs = sorted(d["remaining_demand"])

    reserve_keys = []
    for j, g in pairs:
        permitted = bays if allowed_bays is None else allowed_bays.get((j, g), ())
        reserve_keys.extend((i, j, g) for i in permitted if compatible(d, i, g))
    reserve_keys = sorted(set(reserve_keys))
    flow_keys = sorted(
        (i, j, g, n)
        for (j, g, n) in d["forecast_arrivals"]
        for i, jj, gg in reserve_keys
        if jj == j and gg == g
    )
    inventory_keys = [(i, j, g, n) for i, j, g in reserve_keys for n in periods]

    reserve = m.addVars(reserve_keys, vtype=GRB.INTEGER, lb=0, name="reservation")
    din = m.addVars(flow_keys, vtype=GRB.INTEGER, lb=0, name="din")
    inv = m.addVars(inventory_keys, vtype=GRB.INTEGER, lb=0, name="inventory")
    shortage = m.addVars(
        [(j, g, n) for j, g in pairs for n in periods],
        vtype=GRB.INTEGER,
        lb=0,
        name="shortage",
    )
    if not shortage_allowed:
        for variable in shortage.values():
            variable.UB = 0

    use_keys = sorted({(j, attrs[g]["pod"], i) for i, j, g in reserve_keys})
    use = m.addVars(use_keys, vtype=GRB.BINARY, name="pod_bay_use")
    new_use = m.addVars(use_keys, vtype=GRB.BINARY, name="new_bay")
    height = m.addVars(bays, periods, d["heights"], vtype=GRB.BINARY, name="bay_height")
    share = m.addVars(
        [(j, k, g, n) for j, g in pairs for k in d["blocks"] for n in periods],
        vtype=GRB.INTEGER,
        lb=0,
        name="in_share",
    )
    load = m.addVars(d["blocks"], periods, lb=0, name="block_load")
    avg = m.addVars(periods, lb=0, name="average_load")
    dev = m.addVars(d["blocks"], periods, lb=0, name="balance_dev")

    old = d["previous_reservation"]
    cancellation_keys = sorted(set(reserve_keys) | set(old))
    cancel = m.addVars(cancellation_keys, vtype=GRB.INTEGER, lb=0, name="cancel")
    stability_pairs = sorted(set(pairs) | {(j, g) for (_i, j, g) in old})
    block_cancel = m.addVars(stability_pairs, d["blocks"], lb=0, name="block_cancel")
    reallocation = m.addVars(stability_pairs, lb=0, name="reallocation")
    discretionary = m.addVars(["total"], lb=0, name="discretionary_cancel")

    def locked_at(i: str, n: int) -> float:
        return sum(
            q
            for (ii, old_ship), q in d["locked_inventory"].items()
            if ii == i and d["locked_release_local"].get((ii, old_ship), INF) > n
        )

    def actual_at(i: str, n: int) -> float:
        return sum(
            q
            for (ii, j, _g), q in d["actual_inventory"].items()
            if ii == i and ship_present_at(d, j, n)
        )

    def planned_at(i: str, n: int):
        return gp.quicksum(
            din[ii, j, g, t]
            for ii, j, g, t in flow_keys
            if ii == i and t <= n and ship_present_at(d, j, n)
        )

    last = periods[-1]
    for i in bays:
        related = [key for key in reserve_keys if key[0] == i]
        final_planned = gp.quicksum(reserve[key] for key in related if ship_present_at(d, key[1], last))
        m.addConstr(
            locked_at(i, last) + actual_at(i, last) + final_planned <= d["capacity"][i],
            name=f"final_capacity_{i}",
        )
        for _, j, g in related:
            m.addConstr(reserve[i, j, g] <= d["capacity"][i] * use[j, attrs[g]["pod"], i])
        for n in periods:
            m.addConstr(gp.quicksum(height[i, n, h] for h in d["heights"]) <= 1)
            for (ii, old_ship), h in d["locked_height"].items():
                if ii == i and d["locked_release_local"].get((ii, old_ship), INF) > n:
                    m.addConstr(height[i, n, h] == 1)
            m.addConstr(
                locked_at(i, n) + actual_at(i, n) + planned_at(i, n) <= d["capacity"][i],
                name=f"capacity_{i}_{n}",
            )
            for h in d["heights"]:
                actual_height = sum(
                    q
                    for (ii, j, g), q in d["actual_inventory"].items()
                    if ii == i and attrs[g]["height"] == h and ship_present_at(d, j, n)
                )
                planned_height = gp.quicksum(
                    din[ii, j, g, t]
                    for ii, j, g, t in flow_keys
                    if ii == i and attrs[g]["height"] == h and t <= n and ship_present_at(d, j, n)
                )
                m.addConstr(actual_height + planned_height <= d["capacity"][i] * height[i, n, h])

    for j, g in pairs:
        pair_reserve = [reserve[i, j, g] for i, jj, gg in reserve_keys if jj == j and gg == g]
        pair_flow = [din[i, j, g, n] for i, jj, gg, n in flow_keys if jj == j and gg == g]
        m.addConstr(gp.quicksum(pair_reserve) == gp.quicksum(pair_flow), name=f"reserve_flow_{j}_{g}")
        for n in periods:
            period_flow = gp.quicksum(
                din[i, j, g, n]
                for i, jj, gg, nn in flow_keys
                if jj == j and gg == g and nn == n
            )
            m.addConstr(period_flow + shortage[j, g, n] == d["forecast_arrivals"].get((j, g, n), 0))
            for i, jj, gg in reserve_keys:
                if jj != j or gg != g:
                    continue
                initial = d["actual_inventory"].get((i, j, g), 0)
                cumulative = gp.quicksum(
                    din[ii, jj2, gg2, t]
                    for ii, jj2, gg2, t in flow_keys
                    if ii == i and jj2 == j and gg2 == g and t <= n
                )
                if ship_present_at(d, j, n):
                    m.addConstr(inv[i, j, g, n] == initial + cumulative)
                else:
                    m.addConstr(inv[i, j, g, n] == 0)
                m.addConstr(cumulative <= reserve[i, j, g])
        for k in d["blocks"]:
            for n in periods:
                m.addConstr(
                    share[j, k, g, n]
                    == gp.quicksum(
                        din[i, j, g, n]
                        for i, jj, gg, nn in flow_keys
                        if jj == j and gg == g and nn == n and d["bay_block"][i] == k
                    )
                )

    for key in cancellation_keys:
        current = reserve[key] if key in reserve else 0
        m.addConstr(cancel[key] >= old.get(key, 0) - current)
    for j, pod, i in use_keys:
        was_used = any(
            q > 0 and ii == i and jj == j and attrs[gg]["pod"] == pod
            for (ii, jj, gg), q in old.items()
        )
        if was_used:
            new_use[j, pod, i].UB = 0
        else:
            m.addConstr(new_use[j, pod, i] >= use[j, pod, i])

    mandatory = {}
    for j, g in stability_pairs:
        old_total = sum(q for (_i, jj, gg), q in old.items() if jj == j and gg == g)
        mandatory[j, g] = max(0, old_total - d["remaining_demand"].get((j, g), 0))
        for k in d["blocks"]:
            current_block = gp.quicksum(
                reserve[i, j, g]
                for i, jj, gg in reserve_keys
                if jj == j and gg == g and d["bay_block"][i] == k
            )
            m.addConstr(block_cancel[j, g, k] >= _old_block_amount(d, j, g, k) - current_block)
        pair_shortage = gp.quicksum(
            shortage[jj, gg, n]
            for jj, gg, n in shortage
            if jj == j and gg == g
        )
        m.addConstr(
            reallocation[j, g]
            >= gp.quicksum(block_cancel[j, g, k] for k in d["blocks"])
            - mandatory[j, g]
            - pair_shortage
        )
    cancellation_quantity = cancel.sum()
    mandatory_total = sum(mandatory.values())
    m.addConstr(discretionary["total"] >= cancellation_quantity - mandatory_total - shortage.sum())
    if stability_budget is not None:
        m.addConstr(discretionary["total"] <= float(stability_budget), name="stability_budget")

    for k in d["blocks"]:
        for n in periods:
            base = sum(locked_at(i, n) + actual_at(i, n) for i in d["bays_in_block"][k])
            cumulative = gp.quicksum(
                din[i, j, g, t]
                for i, j, g, t in flow_keys
                if d["bay_block"][i] == k and t <= n and ship_present_at(d, j, n)
            )
            m.addConstr(load[k, n] == base + cumulative)
            m.addConstr(dev[k, n] >= load[k, n] - avg[n])
            m.addConstr(dev[k, n] >= avg[n] - load[k, n])
    for n in periods:
        m.addConstr(len(d["blocks"]) * avg[n] == gp.quicksum(load[k, n] for k in d["blocks"]))

    shortage_obj = shortage.sum()
    block_reallocation = reallocation.sum()
    stability_cost = (
        STABILITY_CANCEL_WEIGHT * cancellation_quantity
        + STABILITY_NEW_BAY_WEIGHT * new_use.sum()
        + STABILITY_BLOCK_REALLOCATION_WEIGHT * block_reallocation
    )
    concentration_raw = use.sum()
    balance_raw = dev.sum()
    distance_raw = gp.quicksum(
        d["distance"][j, k] * share[j, k, g, n]
        for j, g in pairs for k in d["blocks"] for n in periods
    )
    peak = max(d["forecast_outbound"].values(), default=1)
    conflict_raw = gp.quicksum(
        d["forecast_outbound"].get((k, n), 0) / max(1, peak) * share[j, k, g, n]
        for j, g in pairs for k in d["blocks"] for n in periods
    )
    total_forecast = sum(d["forecast_arrivals"].values())
    total_capacity = sum(d["capacity"].values())
    scales = {
        "concentration_scale": max(1, len(use_keys)),
        "balance_scale": max(1, len(periods) * len(d["blocks"]) * total_capacity),
        "distance_scale": max(1, total_forecast * max(d["distance"].values(), default=1)),
        "in_out_conflict_scale": max(1, total_forecast),
    }
    concentration_normalized = concentration_raw / scales["concentration_scale"]
    balance_normalized = balance_raw / scales["balance_scale"]
    distance_normalized = distance_raw / scales["distance_scale"]
    conflict_normalized = conflict_raw / scales["in_out_conflict_scale"]
    if USE_NORMALIZED_OPERATION_OBJECTIVE:
        operation_terms = (concentration_normalized, balance_normalized, distance_normalized, conflict_normalized)
    else:
        operation_terms = (concentration_raw, balance_raw, distance_raw, conflict_raw)
    operations_cost = (
        OPERATION_WEIGHT_CONCENTRATION * operation_terms[0]
        + OPERATION_WEIGHT_BALANCE * operation_terms[1]
        + OPERATION_WEIGHT_DISTANCE * operation_terms[2]
        + OPERATION_WEIGHT_IN_OUT_CONFLICT * operation_terms[3]
    )
    m.ModelSense = GRB.MINIMIZE
    m.setObjectiveN(shortage_obj, 0, priority=3, name="shortage")
    m.setObjectiveN(stability_cost, 1, priority=2, name="stability_cost")
    m.setObjectiveN(operations_cost, 2, priority=1, name="operations_cost")
    m.update()
    variables = {
        "reservation": reserve,
        "din": din,
        "inventory": inv,
        "shortage": shortage,
        "pod_bay_use": use,
        "bay_height": height,
        "cancel": cancel,
        "new_bay": new_use,
        "block_cancel": block_cancel,
        "reallocation": reallocation,
        "discretionary_cancel": discretionary,
        "in_share": share,
        "block_load": load,
    }
    expressions = {
        "predicted_shortage": shortage_obj,
        "cancellation_quantity": cancellation_quantity,
        "mandatory_reduction": float(mandatory_total),
        "discretionary_cancel": discretionary["total"],
        "new_bay_count": new_use.sum(),
        "block_reallocation_quantity": block_reallocation,
        "stability_cost": stability_cost,
        "concentration_raw": concentration_raw,
        "balance_raw": balance_raw,
        "distance_raw": distance_raw,
        "in_out_conflict_raw": conflict_raw,
        "concentration_normalized": concentration_normalized,
        "balance_normalized": balance_normalized,
        "distance_normalized": distance_normalized,
        "in_out_conflict_normalized": conflict_normalized,
        "operations_cost": operations_cost,
        **{name: float(value) for name, value in scales.items()},
    }
    return m, variables, expressions


def extract_rolling_solution(variables: dict, expressions: dict) -> dict:
    def expression_value(value) -> float:
        if hasattr(value, "getValue"):
            return float(value.getValue())
        if hasattr(value, "X"):
            return float(value.X)
        return float(value)
    components = {name: expression_value(value) for name, value in expressions.items()}
    return {
        name: {key: float(variable.X) for key, variable in group.items()}
        for name, group in variables.items()
    } | {"components": components}

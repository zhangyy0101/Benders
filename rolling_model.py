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
    USE_EXACT_STABILITY_BIG_M,
    USE_NORMALIZED_OPERATION_OBJECTIVE,
)

INF = 10**9


def compatible(d: dict, bay: str, group: str) -> bool:
    return d["bay_size"][bay] == d["group_attrs"][group]["size"]


def ship_present_at(d: dict, ship: str, period: int) -> bool:
    """A planned ship occupies capacity strictly before whole-ship release."""
    return d.get("ship_release_local", {}).get(ship, INF) > period


def validate_snapshot_temporal_consistency(d: dict) -> None:
    """Reject positive arrivals at or after the optimizer-visible ship release."""
    violations = [
        (ship, group, period, quantity, d.get("ship_release_local", {}).get(ship))
        for (ship, group, period), quantity in sorted(d["forecast_arrivals"].items())
        if quantity > 0 and not ship_present_at(d, ship, period)
    ]
    if violations:
        preview = violations[:5]
        raise ValueError(
            "forecast arrivals must precede planned ship release; "
            f"violations={preview}, total={len(violations)}"
        )


def existing_support(d: dict, period: int = 0) -> set[tuple[str, str, str]]:
    """Return existing ``(ship, POD, bay)`` support from plans and live inventory."""
    attrs = d["group_attrs"]
    support = {
        (ship, attrs[group]["pod"], bay)
        for (bay, ship, group), quantity in d["previous_reservation"].items()
        if quantity > 0
    }
    support |= {
        (ship, attrs[group]["pod"], bay)
        for (bay, ship, group), quantity in d.get("actual_inventory", {}).items()
        if quantity > 0 and ship_present_at(d, ship, period)
    }
    return support


def existing_blocks(d: dict, ship: str, group: str, period: int = 0) -> set[str]:
    """Return blocks already supporting a ship-group plan or live inventory."""
    planned = {
        d["bay_block"][bay]
        for (bay, j, g), quantity in d["previous_reservation"].items()
        if j == ship and g == group and quantity > 0
    }
    realized = {
        d["bay_block"][bay]
        for (bay, j, g), quantity in d.get("actual_inventory", {}).items()
        if j == ship and g == group and quantity > 0 and ship_present_at(d, j, period)
    }
    return planned | realized


def compute_objective_scales(d: dict) -> dict[str, float]:
    """Compute stage-invariant objective scales from the unrestricted snapshot."""
    attrs = d["group_attrs"]
    full_support = {
        (ship, attrs[group]["pod"], bay)
        for ship, group in d["remaining_demand"]
        for bay in d["bays"]
        if compatible(d, bay, group)
    }
    total_forecast = sum(d["forecast_arrivals"].values())
    return {
        "concentration_scale": float(max(1, len(full_support))),
        "occupancy_balance_scale": float(max(1, len(d["blocks"]) * len(d["periods"]))),
        "distance_scale": float(
            max(1, total_forecast * max(d["distance"].values(), default=1))
        ),
        "in_out_conflict_scale": float(max(1, total_forecast)),
    }


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
    objective_scales: dict[str, float] | None = None,
    use_exact_stability_big_m: bool | None = None,
) -> tuple[gp.Model, dict, dict]:
    m = gp.Model("rolling_6h_bay_allocation")
    m.Params.OutputFlag = 0
    bays, periods, attrs = d["bays"], d["periods"], d["group_attrs"]
    pairs = sorted(d["remaining_demand"])
    exact_stability = (
        USE_EXACT_STABILITY_BIG_M
        if use_exact_stability_big_m is None
        else use_exact_stability_big_m
    )

    reserve_keys = []
    for j, g in pairs:
        permitted = bays if allowed_bays is None else allowed_bays.get((j, g), ())
        reserve_keys.extend((i, j, g) for i in permitted if compatible(d, i, g))
    reserve_keys = sorted(set(reserve_keys))
    flow_keys = sorted(
        (i, j, g, n)
        for (j, g, n) in d["forecast_arrivals"]
        if ship_present_at(d, j, n)
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
    occupancy = m.addVars(d["blocks"], periods, lb=0, name="block_occupancy")
    utilization = m.addVars(d["blocks"], periods, lb=0, ub=1, name="block_utilization")
    avg_utilization = m.addVars(periods, lb=0, ub=1, name="average_utilization")
    utilization_dev = m.addVars(
        d["blocks"], periods, lb=0, name="utilization_deviation"
    )

    old = d["previous_reservation"]
    cancellation_keys = sorted(set(reserve_keys) | set(old))
    cancel = m.addVars(cancellation_keys, vtype=GRB.INTEGER, lb=0, name="cancel")
    cancel_active = (
        m.addVars(cancellation_keys, vtype=GRB.BINARY, name="cancel_active")
        if exact_stability else {}
    )
    stability_pairs = sorted(set(pairs) | {(j, g) for (_i, j, g) in old})
    block_cancel = m.addVars(stability_pairs, d["blocks"], lb=0, name="block_cancel")
    block_cancel_active = (
        m.addVars(
            stability_pairs,
            d["blocks"],
            vtype=GRB.BINARY,
            name="block_cancel_active",
        )
        if exact_stability else {}
    )
    reallocation = m.addVars(stability_pairs, lb=0, name="block_reallocation")
    reallocation_active = (
        m.addVars(
            stability_pairs,
            vtype=GRB.BINARY,
            name="block_reallocation_active",
        )
        if exact_stability else {}
    )
    pair_cancellation = m.addVars(stability_pairs, lb=0, name="pair_cancellation")
    pair_discretionary = m.addVars(
        stability_pairs, lb=0, name="pair_discretionary_cancel"
    )
    discretionary_active = (
        m.addVars(
            stability_pairs,
            vtype=GRB.BINARY,
            name="discretionary_active",
        )
        if exact_stability else {}
    )

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
        raw_cancel = old.get(key, 0) - current
        cancel_m = max(1, old.get(key, 0) + d["capacity"][key[0]])
        m.addConstr(cancel[key] >= raw_cancel)
        if exact_stability:
            m.addConstr(
                cancel[key] <= raw_cancel + cancel_m * (1 - cancel_active[key])
            )
            m.addConstr(cancel[key] <= cancel_m * cancel_active[key])
    support_baseline = existing_support(d, period=0)
    for j, pod, i in use_keys:
        was_used = (j, pod, i) in support_baseline
        if was_used:
            new_use[j, pod, i].UB = 0
        else:
            m.addConstr(new_use[j, pod, i] >= use[j, pod, i])

    mandatory = {}
    for j, g in stability_pairs:
        old_total = sum(q for (_i, jj, gg), q in old.items() if jj == j and gg == g)
        mandatory[j, g] = max(0, old_total - d["remaining_demand"].get((j, g), 0))
        pair_cancel_expression = gp.quicksum(
            cancel[i, jj, gg]
            for i, jj, gg in cancellation_keys
            if jj == j and gg == g
        )
        m.addConstr(pair_cancellation[j, g] == pair_cancel_expression)
        pair_forecast = sum(
            d["forecast_arrivals"].get((j, g, n), 0)
            for n in periods
        )
        exactness_m = max(1, old_total + pair_forecast)
        for k in d["blocks"]:
            current_block = gp.quicksum(
                reserve[i, j, g]
                for i, jj, gg in reserve_keys
                if jj == j and gg == g and d["bay_block"][i] == k
            )
            raw_block_cancel = _old_block_amount(d, j, g, k) - current_block
            m.addConstr(block_cancel[j, g, k] >= raw_block_cancel)
            if exact_stability:
                m.addConstr(
                    block_cancel[j, g, k]
                    <= raw_block_cancel
                    + exactness_m * (1 - block_cancel_active[j, g, k])
                )
                m.addConstr(
                    block_cancel[j, g, k]
                    <= exactness_m * block_cancel_active[j, g, k]
                )
        pair_shortage = gp.quicksum(
            shortage[jj, gg, n]
            for jj, gg, n in shortage
            if jj == j and gg == g
        )
        raw_reallocation = (
            gp.quicksum(block_cancel[j, g, k] for k in d["blocks"])
            - mandatory[j, g]
            - pair_shortage
        )
        m.addConstr(reallocation[j, g] >= raw_reallocation)
        if exact_stability:
            m.addConstr(
                reallocation[j, g]
                <= raw_reallocation
                + exactness_m * (1 - reallocation_active[j, g])
            )
            m.addConstr(
                reallocation[j, g] <= exactness_m * reallocation_active[j, g]
            )
        raw_discretionary = pair_cancellation[j, g] - mandatory[j, g] - pair_shortage
        big_m = exactness_m
        m.addConstr(pair_discretionary[j, g] >= raw_discretionary)
        if exact_stability:
            m.addConstr(
                pair_discretionary[j, g]
                <= raw_discretionary + big_m * (1 - discretionary_active[j, g])
            )
            m.addConstr(
                pair_discretionary[j, g] <= big_m * discretionary_active[j, g]
            )
    cancellation_quantity = cancel.sum()
    mandatory_total = sum(mandatory.values())
    discretionary_total = pair_discretionary.sum()
    if stability_budget is not None:
        m.addConstr(discretionary_total <= float(stability_budget), name="stability_budget")

    for k in d["blocks"]:
        block_capacity = sum(d["capacity"][i] for i in d["bays_in_block"][k])
        for n in periods:
            base = sum(locked_at(i, n) + actual_at(i, n) for i in d["bays_in_block"][k])
            cumulative = gp.quicksum(
                din[i, j, g, t]
                for i, j, g, t in flow_keys
                if d["bay_block"][i] == k and t <= n and ship_present_at(d, j, n)
            )
            m.addConstr(occupancy[k, n] == base + cumulative)
            m.addConstr(block_capacity * utilization[k, n] == occupancy[k, n])
            m.addConstr(utilization_dev[k, n] >= utilization[k, n] - avg_utilization[n])
            m.addConstr(utilization_dev[k, n] >= avg_utilization[n] - utilization[k, n])
    for n in periods:
        m.addConstr(
            len(d["blocks"]) * avg_utilization[n]
            == gp.quicksum(utilization[k, n] for k in d["blocks"])
        )

    shortage_obj = shortage.sum()
    block_reallocation = reallocation.sum()
    stability_cost = (
        STABILITY_CANCEL_WEIGHT * cancellation_quantity
        + STABILITY_NEW_BAY_WEIGHT * new_use.sum()
        + STABILITY_BLOCK_REALLOCATION_WEIGHT * block_reallocation
    )
    concentration_raw = use.sum()
    occupancy_balance_raw = utilization_dev.sum()
    distance_raw = gp.quicksum(
        d["distance"][j, k] * share[j, k, g, n]
        for j, g in pairs for k in d["blocks"] for n in periods
    )
    peak = max(d["forecast_outbound"].values(), default=1)
    conflict_raw = gp.quicksum(
        d["forecast_outbound"].get((k, n), 0) / max(1, peak) * share[j, k, g, n]
        for j, g in pairs for k in d["blocks"] for n in periods
    )
    scales = dict(objective_scales or compute_objective_scales(d))
    concentration_normalized = concentration_raw / scales["concentration_scale"]
    occupancy_balance_normalized = (
        occupancy_balance_raw / scales["occupancy_balance_scale"]
    )
    distance_normalized = distance_raw / scales["distance_scale"]
    conflict_normalized = conflict_raw / scales["in_out_conflict_scale"]
    if USE_NORMALIZED_OPERATION_OBJECTIVE:
        operation_terms = (
            concentration_normalized,
            occupancy_balance_normalized,
            distance_normalized,
            conflict_normalized,
        )
    else:
        operation_terms = (
            concentration_raw,
            occupancy_balance_raw,
            distance_raw,
            conflict_raw,
        )
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
        "block_reallocation": reallocation,
        "pair_cancellation": pair_cancellation,
        "pair_discretionary_cancel": pair_discretionary,
        "in_share": share,
        "block_occupancy": occupancy,
        "block_utilization": utilization,
    }
    expressions = {
        "predicted_shortage": shortage_obj,
        "cancellation_quantity": cancellation_quantity,
        "mandatory_reduction": float(mandatory_total),
        "discretionary_cancel": discretionary_total,
        "new_bay_count": new_use.sum(),
        "block_reallocation_quantity": block_reallocation,
        "stability_cost": stability_cost,
        "concentration_raw": concentration_raw,
        "occupancy_balance_raw": occupancy_balance_raw,
        "distance_raw": distance_raw,
        "in_out_conflict_raw": conflict_raw,
        "concentration_normalized": concentration_normalized,
        "occupancy_balance_normalized": occupancy_balance_normalized,
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

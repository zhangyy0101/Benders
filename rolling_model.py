"""Six-hour stability-aware rolling bay-slot allocation MIP."""
from __future__ import annotations

from collections import defaultdict

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


def solve_full_horizon_packing_oracle(
    case: dict,
    *,
    flow: dict[tuple[str, str, int], int] | None = None,
    release_basis: str = "realized",
    time_limit: float = 60.0,
    threads: int = 1,
    seed: int = 0,
    return_witness: bool = False,
    stop_after_classification: bool = True,
) -> dict:
    """Certify full-information integer packing feasibility over the case horizon.

    The oracle is deliberately independent of forecasts, rolling decisions, and
    repair logic.  It minimizes integer unplaced demand using the realized or
    planned whole-ship release dates.  A zero-shortage incumbent is a feasibility
    certificate because shortage is nonnegative; a positive value establishes
    structural overload only after optimality has been proved.
    """
    if release_basis not in {"realized", "planned"}:
        raise ValueError("release_basis must be 'realized' or 'planned'")
    if time_limit <= 0:
        raise ValueError("time_limit must be positive")
    if threads <= 0:
        raise ValueError("threads must be positive")

    release_key = (
        "realized_ship_release_period"
        if release_basis == "realized"
        else "planned_ship_release_period"
    )
    releases = case[release_key]
    raw_demand = flow if flow is not None else case["true_flow"]
    if any(
        int(quantity) != quantity or quantity < 0
        for quantity in raw_demand.values()
    ):
        raise ValueError("oracle flow quantities must be nonnegative integers")
    demand = {
        (ship, group, int(period)): int(quantity)
        for (ship, group, period), quantity in raw_demand.items()
        if int(quantity) > 0
    }

    bays = tuple(case["bays"])
    heights = tuple(case["heights"])
    attrs = case["group_attrs"]
    old_releases = case.get("old_release_period", {})
    locked = case.get("locked_initial", {})
    locked_height = case.get("locked_height_initial", {})
    for bay in bays:
        if case["capacity"][bay] <= 0:
            raise ValueError(f"bay capacity must be positive: {bay}")
    for ship, group, _period in demand:
        if ship not in releases:
            raise ValueError(f"missing {release_basis} release for ship {ship}")
        if group not in attrs:
            raise ValueError(f"missing attributes for group {group}")
        if attrs[group]["height"] not in heights:
            raise ValueError(f"unsupported height for group {group}")

    locked_by_bay: dict[str, list[tuple[str, int, str, int]]] = defaultdict(list)
    for (bay, old_ship), raw_quantity in locked.items():
        quantity = int(raw_quantity)
        if quantity <= 0:
            continue
        if bay not in case["capacity"]:
            raise ValueError(f"locked inventory references unknown bay {bay}")
        height = locked_height.get((bay, old_ship))
        if height not in heights:
            raise ValueError(
                f"locked inventory lacks a valid height: {(bay, old_ship)}"
            )
        release = int(old_releases.get(old_ship, INF))
        locked_by_bay[bay].append((old_ship, quantity, height, release))

    for bay, records in locked_by_bay.items():
        live_at_zero = [record for record in records if record[3] > 0]
        if sum(record[1] for record in live_at_zero) > case["capacity"][bay]:
            raise ValueError(f"locked inventory exceeds capacity in bay {bay}")
        if len({record[2] for record in live_at_zero}) > 1:
            raise ValueError(f"locked inventory mixes heights in bay {bay}")

    last_arrival = max((period for _ship, _group, period in demand), default=0)
    horizon = tuple(range(0, max(0, last_arrival) + 1))
    compatible_bays: dict[tuple[str, str, int], tuple[str, ...]] = {}
    late_flow_quantity = 0
    place_keys: list[tuple[str, str, str, int]] = []
    for key in sorted(demand):
        ship, group, arrival = key
        if arrival < 0:
            raise ValueError("oracle arrival periods must be nonnegative")
        if arrival >= int(releases[ship]):
            compatible_bays[key] = ()
            late_flow_quantity += demand[key]
            continue
        permitted = tuple(
            bay
            for bay in bays
            if case["bay_size"][bay] == attrs[group]["size"]
        )
        compatible_bays[key] = permitted
        place_keys.extend((bay, ship, group, arrival) for bay in permitted)

    model = gp.Model("full_horizon_integer_packing_oracle")
    model.Params.OutputFlag = 0
    model.Params.Threads = int(threads)
    model.Params.Seed = int(seed)
    model.Params.TimeLimit = float(time_limit)
    model.Params.MIPGap = 0.0

    placement = model.addVars(
        place_keys,
        vtype=GRB.INTEGER,
        lb=0,
        name="place",
    )
    shortage = model.addVars(
        sorted(demand),
        vtype=GRB.INTEGER,
        lb=0,
        name="shortage",
    )
    height_choice = model.addVars(
        [(bay, period, height) for bay in bays for period in horizon for height in heights],
        vtype=GRB.BINARY,
        name="height",
    )

    placement_by_bay: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for key in place_keys:
        placement_by_bay[key[0]].append(key)
    for demand_key, quantity in demand.items():
        ship, group, arrival = demand_key
        model.addConstr(
            gp.quicksum(
                placement[bay, ship, group, arrival]
                for bay in compatible_bays[demand_key]
            )
            + shortage[demand_key]
            == quantity,
            name=f"flow[{ship},{group},{arrival}]",
        )

    for bay in bays:
        bay_placements = placement_by_bay[bay]
        for period in horizon:
            live_locked = [
                record for record in locked_by_bay.get(bay, ()) if record[3] > period
            ]
            locked_quantity = sum(record[1] for record in live_locked)
            live_placements = [
                key
                for key in bay_placements
                if key[3] <= period < int(releases[key[1]])
            ]
            model.addConstr(
                locked_quantity
                + gp.quicksum(placement[key] for key in live_placements)
                <= case["capacity"][bay],
                name=f"capacity[{bay},{period}]",
            )
            model.addConstr(
                gp.quicksum(
                    height_choice[bay, period, height] for height in heights
                )
                <= 1,
                name=f"one_height[{bay},{period}]",
            )
            locked_heights = {record[2] for record in live_locked}
            if locked_heights:
                locked_value = next(iter(locked_heights))
                model.addConstr(
                    height_choice[bay, period, locked_value] == 1,
                    name=f"locked_height[{bay},{period}]",
                )
            for height in heights:
                same_height = [
                    key
                    for key in live_placements
                    if attrs[key[2]]["height"] == height
                ]
                model.addConstr(
                    gp.quicksum(placement[key] for key in same_height)
                    <= case["capacity"][bay]
                    * height_choice[bay, period, height],
                    name=f"height_capacity[{bay},{period},{height}]",
                )

    total_shortage = shortage.sum()
    model.setObjective(total_shortage, GRB.MINIMIZE)

    def classification_callback(active_model: gp.Model, where: int) -> None:
        if not stop_after_classification:
            return
        if where == GRB.Callback.MIPSOL:
            incumbent = active_model.cbGet(GRB.Callback.MIPSOL_OBJ)
            if incumbent <= 0.5:
                active_model.terminate()
        elif where == GRB.Callback.MIP:
            lower_bound = active_model.cbGet(GRB.Callback.MIP_OBJBND)
            if lower_bound > 0.5:
                active_model.terminate()

    model.optimize(classification_callback)

    status = int(model.Status)
    solution_count = int(model.SolCount)
    objective = float(model.ObjVal) if solution_count else None
    objective_bound = (
        float(model.ObjBound)
        if status not in {GRB.INFEASIBLE, GRB.INF_OR_UNBD}
        else None
    )
    zero_shortage = objective is not None and objective <= 0.5
    positive_shortage = objective_bound is not None and objective_bound > 0.5
    proved_optimal = status == GRB.OPTIMAL or zero_shortage
    if zero_shortage:
        classification = "feasible"
    elif positive_shortage:
        classification = "overloaded"
    else:
        classification = "unknown"

    result = {
        "classification": classification,
        "release_basis": release_basis,
        "minimum_shortage": (
            int(round(objective)) if objective is not None and proved_optimal else None
        ),
        "incumbent_shortage": (
            int(round(objective)) if objective is not None else None
        ),
        "objective_bound": objective_bound,
        "shortage_lower_bound": (
            max(0, int(objective_bound - 1e-6) + 1)
            if positive_shortage
            else 0 if objective_bound is not None else None
        ),
        "proved_optimal": proved_optimal,
        "zero_shortage_certificate": zero_shortage,
        "positive_shortage_certificate": positive_shortage,
        "solver_status": status,
        "solution_count": solution_count,
        "runtime_seconds": float(model.Runtime),
        "node_count": float(model.NodeCount),
        "total_demand": int(sum(demand.values())),
        "late_flow_quantity": int(late_flow_quantity),
        "horizon_periods": len(horizon),
        "placement_variable_count": len(place_keys),
        "model_variable_count": int(model.NumVars),
        "model_constraint_count": int(model.NumConstrs),
    }
    if return_witness and solution_count:
        result["placement"] = {
            key: int(round(variable.X))
            for key, variable in placement.items()
            if variable.X > 0.5
        }
        result["shortage"] = {
            key: int(round(variable.X))
            for key, variable in shortage.items()
            if variable.X > 0.5
        }
    model.dispose()
    return result


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
    permitted_bays_by_pair: dict[tuple[str, str], tuple[str, ...]] = {}
    for j, g in pairs:
        permitted = bays if allowed_bays is None else allowed_bays.get((j, g), ())
        compatible_bays = tuple(
            sorted({i for i in permitted if compatible(d, i, g)})
        )
        permitted_bays_by_pair[j, g] = compatible_bays
        reserve_keys.extend((i, j, g) for i in compatible_bays)
    reserve_keys = sorted(set(reserve_keys))
    forecast_periods_by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
    pair_set = set(pairs)
    for j, g, n in sorted(d["forecast_arrivals"]):
        if (j, g) in pair_set and ship_present_at(d, j, n):
            forecast_periods_by_pair[j, g].append(n)
    flow_keys = sorted(
        (i, j, g, n)
        for j, g in pairs
        for n in forecast_periods_by_pair[j, g]
        for i in permitted_bays_by_pair[j, g]
    )
    inventory_keys = [(i, j, g, n) for i, j, g in reserve_keys for n in periods]

    reserve_by_pair: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    reserve_by_bay: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    reserve_by_pair_block: dict[
        tuple[str, str, str], list[tuple[str, str, str]]
    ] = defaultdict(list)
    for key in reserve_keys:
        i, j, g = key
        reserve_by_pair[j, g].append(key)
        reserve_by_bay[i].append(key)
        reserve_by_pair_block[j, g, d["bay_block"][i]].append(key)

    flow_by_pair: dict[
        tuple[str, str], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    flow_by_pair_period: dict[
        tuple[str, str, int], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    flow_by_bay: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    flow_by_bay_height: dict[
        tuple[str, str], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    flow_by_bay_pair: dict[
        tuple[str, str, str], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    flow_by_pair_block_period: dict[
        tuple[str, str, str, int], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    flow_by_block: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for key in flow_keys:
        i, j, g, n = key
        block = d["bay_block"][i]
        flow_by_pair[j, g].append(key)
        flow_by_pair_period[j, g, n].append(key)
        flow_by_bay[i].append(key)
        flow_by_bay_height[i, attrs[g]["height"]].append(key)
        flow_by_bay_pair[i, j, g].append(key)
        flow_by_pair_block_period[j, g, block, n].append(key)
        flow_by_block[block].append(key)

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
    cancellation_by_pair: dict[
        tuple[str, str], list[tuple[str, str, str]]
    ] = defaultdict(list)
    for key in cancellation_keys:
        cancellation_by_pair[key[1], key[2]].append(key)
    old_total_by_pair: dict[tuple[str, str], float] = defaultdict(float)
    old_block_by_pair: dict[tuple[str, str, str], float] = defaultdict(float)
    for (i, j, g), quantity in old.items():
        old_total_by_pair[j, g] += quantity
        old_block_by_pair[j, g, d["bay_block"][i]] += quantity
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

    locked_entries_by_bay: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (i, old_ship), quantity in d["locked_inventory"].items():
        locked_entries_by_bay[i].append((old_ship, quantity))
    locked_heights_by_bay: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (i, old_ship), height_value in d["locked_height"].items():
        locked_heights_by_bay[i].append((old_ship, height_value))
    actual_entries_by_bay: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for (i, j, g), quantity in d["actual_inventory"].items():
        actual_entries_by_bay[i].append((j, g, quantity))

    locked_amount: dict[tuple[str, int], float] = {}
    actual_amount: dict[tuple[str, int], float] = {}
    actual_height_amount: dict[tuple[str, int, str], float] = {}
    planned_capacity_keys: dict[
        tuple[str, int], tuple[tuple[str, str, str, int], ...]
    ] = {}
    planned_height_keys: dict[
        tuple[str, int, str], tuple[tuple[str, str, str, int], ...]
    ] = {}
    for i in bays:
        for n in periods:
            locked_amount[i, n] = sum(
                quantity
                for old_ship, quantity in locked_entries_by_bay[i]
                if d["locked_release_local"].get((i, old_ship), INF) > n
            )
            actual_amount[i, n] = sum(
                quantity
                for j, _g, quantity in actual_entries_by_bay[i]
                if ship_present_at(d, j, n)
            )
            planned_capacity_keys[i, n] = tuple(
                key
                for key in flow_by_bay[i]
                if key[3] <= n and ship_present_at(d, key[1], n)
            )
            for h in d["heights"]:
                actual_height_amount[i, n, h] = sum(
                    quantity
                    for j, g, quantity in actual_entries_by_bay[i]
                    if attrs[g]["height"] == h and ship_present_at(d, j, n)
                )
                planned_height_keys[i, n, h] = tuple(
                    key
                    for key in flow_by_bay_height[i, h]
                    if key[3] <= n and ship_present_at(d, key[1], n)
                )

    last = periods[-1]
    for i in bays:
        related = reserve_by_bay[i]
        final_planned = gp.quicksum(
            reserve[key] for key in related if ship_present_at(d, key[1], last)
        )
        m.addConstr(
            locked_amount[i, last]
            + actual_amount[i, last]
            + final_planned
            <= d["capacity"][i],
            name=f"final_capacity_{i}",
        )
        for _, j, g in related:
            m.addConstr(reserve[i, j, g] <= d["capacity"][i] * use[j, attrs[g]["pod"], i])
        for n in periods:
            m.addConstr(gp.quicksum(height[i, n, h] for h in d["heights"]) <= 1)
            for old_ship, h in locked_heights_by_bay[i]:
                if d["locked_release_local"].get((i, old_ship), INF) > n:
                    m.addConstr(height[i, n, h] == 1)
            m.addConstr(
                locked_amount[i, n]
                + actual_amount[i, n]
                + gp.quicksum(din[key] for key in planned_capacity_keys[i, n])
                <= d["capacity"][i],
                name=f"capacity_{i}_{n}",
            )
            for h in d["heights"]:
                planned_height = gp.quicksum(
                    din[key] for key in planned_height_keys[i, n, h]
                )
                m.addConstr(
                    actual_height_amount[i, n, h] + planned_height
                    <= d["capacity"][i] * height[i, n, h]
                )

    for j, g in pairs:
        pair_reserve = [reserve[key] for key in reserve_by_pair[j, g]]
        pair_flow = [din[key] for key in flow_by_pair[j, g]]
        m.addConstr(gp.quicksum(pair_reserve) == gp.quicksum(pair_flow), name=f"reserve_flow_{j}_{g}")
        for n in periods:
            period_flow = gp.quicksum(
                din[key] for key in flow_by_pair_period[j, g, n]
            )
            m.addConstr(period_flow + shortage[j, g, n] == d["forecast_arrivals"].get((j, g, n), 0))
            for i, _j, _g in reserve_by_pair[j, g]:
                initial = d["actual_inventory"].get((i, j, g), 0)
                cumulative = gp.quicksum(
                    din[key]
                    for key in flow_by_bay_pair[i, j, g]
                    if key[3] <= n
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
                        din[key]
                        for key in flow_by_pair_block_period[j, g, k, n]
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
        old_total = old_total_by_pair[j, g]
        mandatory[j, g] = max(0, old_total - d["remaining_demand"].get((j, g), 0))
        pair_cancel_expression = gp.quicksum(
            cancel[key] for key in cancellation_by_pair[j, g]
        )
        m.addConstr(pair_cancellation[j, g] == pair_cancel_expression)
        pair_forecast = sum(
            d["forecast_arrivals"].get((j, g, n), 0)
            for n in periods
        )
        exactness_m = max(1, old_total + pair_forecast)
        for k in d["blocks"]:
            current_block = gp.quicksum(
                reserve[key] for key in reserve_by_pair_block[j, g, k]
            )
            raw_block_cancel = old_block_by_pair[j, g, k] - current_block
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
        pair_shortage = (
            gp.quicksum(shortage[j, g, n] for n in periods)
            if (j, g) in pair_set
            else gp.LinExpr()
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
            base = sum(
                locked_amount[i, n] + actual_amount[i, n]
                for i in d["bays_in_block"][k]
            )
            cumulative = gp.quicksum(
                din[key]
                for key in flow_by_block[k]
                if key[3] <= n and ship_present_at(d, key[1], n)
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
    normalized_operations_score = (
        OPERATION_WEIGHT_CONCENTRATION * concentration_normalized
        + OPERATION_WEIGHT_BALANCE * occupancy_balance_normalized
        + OPERATION_WEIGHT_DISTANCE * distance_normalized
        + OPERATION_WEIGHT_IN_OUT_CONFLICT * conflict_normalized
    )
    m.ModelSense = GRB.MINIMIZE
    m.setObjectiveN(shortage_obj, 0, priority=3, name="shortage")
    m.setObjectiveN(stability_cost, 1, priority=2, name="stability_cost")
    m.setObjectiveN(
        normalized_operations_score,
        2,
        priority=1,
        name="normalized_operations_score",
    )
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
        "normalized_operations_score": normalized_operations_score,
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

    def variable_value(variable) -> float | int:
        value = float(variable.X)
        if variable.VType in (GRB.BINARY, GRB.INTEGER):
            return int(round(value))
        return value

    components = {name: expression_value(value) for name, value in expressions.items()}
    return {
        name: {key: variable_value(variable) for key, variable in group.items()}
        for name, group in variables.items()
    } | {"components": components}

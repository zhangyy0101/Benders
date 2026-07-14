"""Short-lived aggregate master used only to guide later primal construction.

This module deliberately does not evaluate recourse and does not produce an upper
bound.  Every solve attempt, including the LP fallback, shares one wall-clock
deadline.
"""
from __future__ import annotations

import time

from gurobipy import GRB

from model_master import build_master_model, extract_master_point


TOLERANCE = 1e-7


def _status_name(status) -> str:
    return {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.SUBOPTIMAL: "SUBOPTIMAL",
    }.get(status, "NOT_SOLVED" if status is None else str(status))


def _empty_diagnostics() -> dict:
    return {
        "positive_x_count": 0,
        "positive_alloc_count": 0,
        "positive_z_count": 0,
        "fractional_x_count": 0,
        "fractional_alloc_count": 0,
        "aggregate_flow_by_ship_size_block": {},
        "alloc_support_by_ship_group_bay": {},
        "x_support_by_ship_bay": {},
    }


def _diagnostics(data, x, alloc_boxes, aggregate_z) -> dict:
    positive_x = {key: value for key, value in x.items() if value > TOLERANCE}
    positive_alloc = {key: value for key, value in alloc_boxes.items() if value > TOLERANCE}
    positive_z = {key: value for key, value in aggregate_z.items() if value > TOLERANCE}
    flow = {}
    for (j, k, size, _n), value in positive_z.items():
        key = (j, size, k)
        flow[key] = flow.get(key, 0.0) + value
    alloc_support = {}
    for (i, j, group, _n), value in positive_alloc.items():
        key = (j, group, i)
        item = alloc_support.setdefault(key, {"max": 0.0, "sum": 0.0})
        item["max"] = max(item["max"], value)
        item["sum"] += value
    durations = {n: float(data["Intervals"][n]["dur"]) for n in data["N"]}
    x_support = {}
    for (i, j, n), value in positive_x.items():
        key = (j, i)
        x_support[key] = x_support.get(key, 0.0) + durations[n] * value
    return {
        "positive_x_count": len(positive_x),
        "positive_alloc_count": len(positive_alloc),
        "positive_z_count": len(positive_z),
        "fractional_x_count": sum(TOLERANCE < value < 1.0 - TOLERANCE for value in x.values()),
        "fractional_alloc_count": sum(
            value > TOLERANCE and abs(value - round(value)) > TOLERANCE
            for value in alloc_boxes.values()
        ),
        "aggregate_flow_by_ship_size_block": flow,
        "alloc_support_by_ship_group_bay": alloc_support,
        "x_support_by_ship_bay": x_support,
    }


def _extract(model, variables, context):
    point = extract_master_point(variables)
    z_vars = context["aggregate"]["variables"]["z"]
    aggregate_z = {key: float(var.X) for key, var in z_vars.items()}
    return point["x"], point["alloc_boxes"], aggregate_z


def _relaxed_views(relaxed, variables, context):
    mapped = {
        "x": {key: relaxed.getVarByName(var.VarName) for key, var in variables["x"].items()},
        "alloc_boxes": {key: relaxed.getVarByName(var.VarName) for key, var in variables["alloc_boxes"].items()},
        "eta": relaxed.getVarByName(variables["eta"].VarName),
    }
    z = context["aggregate"]["variables"]["z"]
    mapped_context = {"aggregate": {"variables": {"z": {key: relaxed.getVarByName(var.VarName) for key, var in z.items()}}}}
    return mapped, mapped_context


def solve_aggregate_guide(
    data,
    weights,
    *,
    time_limit: float,
    threads: int = 1,
    seed: int = 0,
    alloc_domain: str = "integer",
    concentration_enabled: bool = True,
) -> dict:
    """Return aggregate support information without claiming an exact UB."""
    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit))
    build_runtime = 0.0
    optimization_runtime = 0.0
    last_status = None
    errors = []

    def remaining():
        return max(0.0, deadline - time.perf_counter())

    estimated_group_bay_time = (len(data["I_list"]) *
                                sum(len(data.get("ActiveGroupsByShip", {}).get(j, data.get("G", data["S"])))
                                    for j in data["J_new"]) * len(data["N"]))
    if estimated_group_bay_time > 100_000:
        diagnostics = _empty_diagnostics(); diagnostics["size_deadline_guard"] = estimated_group_bay_time
        return {"ok": True, "source": "static_fallback", "runtime": time.perf_counter() - started,
                "model_build_runtime": 0.0, "optimization_runtime": 0.0,
                "status_name": "SKIPPED_SIZE_DEADLINE", "guide_objective": None, "guide_bound": None,
                "x": {}, "alloc_boxes": {}, "aggregate_z": {}, "diagnostics": diagnostics}
    solve_sequence = ((False, "mip_incumbent"), (True, "lp_fallback"))
    for relax, source in solve_sequence:
        if remaining() <= 0:
            break
        model = None
        try:
            build_started = time.perf_counter()
            model, variables, context = build_master_model(
                data,
                weights,
                alloc_domain=alloc_domain,
                relax=relax,
                add_valid_inequalities=False,
                aggregate_recourse_lb=True,
                analytic_recourse_lb=False,
                concentration_enabled=concentration_enabled,
            )
            build_runtime += time.perf_counter() - build_started
            available = remaining()
            if available <= 0:
                break
            model.Params.OutputFlag = 0
            model.Params.Threads = int(threads or 1)
            model.Params.Seed = int(seed)
            model.Params.MIPFocus = 1
            model.Params.Heuristics = 0.5
            model.Params.MIPGap = 0.10
            if relax:
                model.Params.Method = 1
            # Large masters reserve time for a relaxation of the already-built model.
            # This prevents an unsuccessful MIP search from consuming the entire guide deadline.
            reserve_relaxation = not relax and build_runtime > .5
            model.Params.TimeLimit = min(available, .25) if reserve_relaxation else available
            optimize_started = time.perf_counter()
            model.optimize()
            optimization_runtime += time.perf_counter() - optimize_started
            last_status = model.Status
            if model.SolCount:
                x, alloc_boxes, aggregate_z = _extract(model, variables, context)
                guide_objective = float(model.ObjVal)
                guide_bound = float(model.ObjBound)
                model.dispose()
                model = None
                result = {
                    "ok": True,
                    "source": source,
                    "runtime": time.perf_counter() - started,
                    "model_build_runtime": build_runtime,
                    "optimization_runtime": optimization_runtime,
                    "status_name": _status_name(last_status),
                    "guide_objective": guide_objective,
                    "guide_bound": guide_bound,
                    "x": x,
                    "alloc_boxes": alloc_boxes,
                    "aggregate_z": aggregate_z,
                    "diagnostics": _diagnostics(data, x, alloc_boxes, aggregate_z),
                }
                return result
            if reserve_relaxation and remaining() > 0:
                relaxed = model.relax()
                relaxed.update()
                relaxed_variables, relaxed_context = _relaxed_views(relaxed, variables, context)
                model.dispose(); model = relaxed
                available = remaining()
                model.Params.OutputFlag = 0
                model.Params.Threads = int(threads or 1)
                model.Params.TimeLimit = available
                optimize_started = time.perf_counter(); model.optimize()
                optimization_runtime += time.perf_counter() - optimize_started
                last_status = model.Status
                if model.SolCount:
                    x, alloc_boxes, aggregate_z = _extract(model, relaxed_variables, relaxed_context)
                    guide_objective, guide_bound = float(model.ObjVal), float(model.ObjBound)
                    model.dispose(); model = None
                    return {"ok": True, "source": "lp_fallback", "runtime": time.perf_counter() - started,
                            "model_build_runtime": build_runtime, "optimization_runtime": optimization_runtime,
                            "status_name": _status_name(last_status), "guide_objective": guide_objective,
                            "guide_bound": guide_bound, "x": x, "alloc_boxes": alloc_boxes,
                            "aggregate_z": aggregate_z,
                            "diagnostics": _diagnostics(data, x, alloc_boxes, aggregate_z)}
        except Exception as exc:  # A guide failure must be harmless to later AGFR stages.
            errors.append(f"{source}: {type(exc).__name__}: {exc}")
        finally:
            if model is not None:
                model.dispose()

    diagnostics = _empty_diagnostics()
    if errors:
        diagnostics["fallback_errors"] = errors
    return {
        "ok": True,
        "source": "static_fallback",
        "runtime": time.perf_counter() - started,
        "model_build_runtime": build_runtime,
        "optimization_runtime": optimization_runtime,
        "status_name": _status_name(last_status),
        "guide_objective": None,
        "guide_bound": None,
        "x": {},
        "alloc_boxes": {},
        "aggregate_z": {},
        "diagnostics": diagnostics,
    }

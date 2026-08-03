"""Adapted published baselines under the common rolling-snapshot contract."""
from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable, TypeAlias

from config import (
    EXTERNAL_BASELINE_PROTOCOL,
    WALL_TIME_TOLERANCE_SECONDS,
)
from rolling_model import (
    compatible,
    compute_objective_scales,
    resolve_operation_weights,
    ship_present_at,
)
from rolling_solver import (
    CONFIGURATIONS as CORE_CONFIGURATIONS,
    canonical_stability_metrics,
    postprocessing_reserve_seconds,
    validate_rolling_solution,
)

Pair: TypeAlias = tuple[str, str]
Job: TypeAlias = tuple[int, int, str, str, int]

LITERATURE_CONFIGURATIONS = ("kp_dos", "kp_sg", "dra_rpm")
CONFIGURATIONS = CORE_CONFIGURATIONS + LITERATURE_CONFIGURATIONS

KP_SG_MAX_ITERATIONS = 200
KP_SG_INITIAL_LAMBDA = 2.0
KP_SG_NO_IMPROVEMENT_WINDOW = 5
KP_SG_MIN_LAMBDA = 0.025
KP_SHORTAGE_PENALTY = 1_000.0
DRA_MU = 0.5
DRA_NU = 0.5
DRA_HISTORY_DISCOUNT = 0.8
DRA_HISTORY_LIMIT = 12
DRA_PARAMETER_PROFILES = {
    "frozen": {
        "mu": DRA_MU,
        "nu": DRA_NU,
        "history_discount": DRA_HISTORY_DISCOUNT,
    },
    "mu_low": {
        "mu": 0.25,
        "nu": DRA_NU,
        "history_discount": DRA_HISTORY_DISCOUNT,
    },
    "mu_high": {
        "mu": 0.75,
        "nu": DRA_NU,
        "history_discount": DRA_HISTORY_DISCOUNT,
    },
    "nu_low": {
        "mu": DRA_MU,
        "nu": 0.25,
        "history_discount": DRA_HISTORY_DISCOUNT,
    },
    "nu_high": {
        "mu": DRA_MU,
        "nu": 0.75,
        "history_discount": DRA_HISTORY_DISCOUNT,
    },
    "discount_low": {
        "mu": DRA_MU,
        "nu": DRA_NU,
        "history_discount": 0.60,
    },
    "discount_high": {
        "mu": DRA_MU,
        "nu": DRA_NU,
        "history_discount": 0.95,
    },
}

BASELINE_SPECS = {
    "kp_dos": {
        "family": "Kim-Park 2003",
        "method": "least-duration-of-stay",
        "doi": "10.1016/S0377-2217(02)00333-8",
        "source_pdf_sha256": (
            "269d3c6b102de2cc2e1f46db563e4b9452915df2a2db8d519c4d3463286fe15c"
        ),
        "fidelity": "adapted_algorithmic_core",
        "native_direction": "minimize",
    },
    "kp_sg": {
        "family": "Kim-Park 2003",
        "method": "subgradient-lagrangian",
        "doi": "10.1016/S0377-2217(02)00333-8",
        "source_pdf_sha256": (
            "269d3c6b102de2cc2e1f46db563e4b9452915df2a2db8d519c4d3463286fe15c"
        ),
        "fidelity": "adapted_publisher_full_text",
        "native_direction": "minimize",
    },
    "dra_rpm": {
        "family": "Xuan et al. 2024",
        "method": "dynamic-reward-penalty",
        "doi": "10.1016/j.heliyon.2024.e37817",
        "source_pdf_sha256": (
            "19d672e7fed8a017863a67566ca84ea573a3ab035b7fe21e4f8882d026aee466"
        ),
        "fidelity": "adapted_open_full_text",
        "native_direction": "maximize",
    },
}


def literature_baseline_metadata() -> dict[str, object]:
    """Return frozen source and adaptation metadata for experiment manifests."""
    return {
        "protocol": EXTERNAL_BASELINE_PROTOCOL,
        "methods": BASELINE_SPECS,
        "common_decoder": (
            "integer_best_fit_with_capacity_size_height_and_lifecycle"
        ),
        "kp_sg": {
            "max_iterations": KP_SG_MAX_ITERATIONS,
            "relaxed_constraint": "shared_block_period_capacity",
            "decomposition": "vessel_with_reverse_stage_assignment",
            "step_rule": "held_wolfe_upper_bound_gap_over_subgradient_norm",
            "initial_lambda": KP_SG_INITIAL_LAMBDA,
            "no_improvement_window": KP_SG_NO_IMPROVEMENT_WINDOW,
            "lambda_reduction": 0.5,
            "minimum_lambda": KP_SG_MIN_LAMBDA,
            "parameter_provenance": (
                "initial_lambda_is_standard_convention;"
                "window_5_is_lower_endpoint_of_paper_reported_5_to_10"
            ),
            "feasibility_recovery": (
                "paper_priority_then_common_integer_bay_decoder"
            ),
        },
        "dra_rpm": {
            "mu": DRA_MU,
            "nu": DRA_NU,
            "history_discount": DRA_HISTORY_DISCOUNT,
            "history_limit": DRA_HISTORY_LIMIT,
            "reward_choice": "maximize_equation_27",
            "operation_count_proxy": "normalized_outbound_forecast_0_to_10",
            "distance_cutoff": "inactive_no_common_business_threshold",
            "main_parameter_profile": "frozen",
            "sensitivity_profiles": DRA_PARAMETER_PROFILES,
        },
    }


def baseline_row_metadata(
    configuration: str,
    parameter_profile: str = "frozen",
) -> dict[str, object]:
    """Return scalar method identity for one CSV row."""
    if parameter_profile not in DRA_PARAMETER_PROFILES:
        raise ValueError(
            "parameter_profile must be one of "
            f"{tuple(DRA_PARAMETER_PROFILES)}"
        )
    profile = (
        parameter_profile if configuration == "dra_rpm" else "not_applicable"
    )
    parameters: dict[str, float] | None = (
        DRA_PARAMETER_PROFILES[parameter_profile]
        if configuration == "dra_rpm" else None
    )
    if configuration not in LITERATURE_CONFIGURATIONS:
        return {
            "baseline_protocol": None,
            "baseline_family": None,
            "baseline_method": None,
            "baseline_doi": None,
            "baseline_fidelity": None,
            "baseline_parameter_profile": profile,
            "baseline_mu": None,
            "baseline_nu": None,
            "baseline_history_discount": None,
        }
    spec = BASELINE_SPECS[configuration]
    return {
        "baseline_protocol": EXTERNAL_BASELINE_PROTOCOL,
        "baseline_family": spec["family"],
        "baseline_method": spec["method"],
        "baseline_doi": spec["doi"],
        "baseline_fidelity": spec["fidelity"],
        "baseline_parameter_profile": profile,
        "baseline_mu": parameters["mu"] if parameters else None,
        "baseline_nu": parameters["nu"] if parameters else None,
        "baseline_history_discount": (
            parameters["history_discount"] if parameters else None
        ),
    }


def _jobs(d: dict) -> list[Job]:
    """Return positive arrival jobs as period/release/ship/group/quantity."""
    return sorted(
        (
            period,
            int(d["ship_release_local"].get(ship, 10**9)),
            ship,
            group,
            int(round(quantity)),
        )
        for (ship, group, period), quantity in d["forecast_arrivals"].items()
        if quantity > 0
    )


def _occupied_periods(d: dict, ship: str, arrival_period: int) -> tuple[int, ...]:
    return tuple(
        period
        for period in d["periods"]
        if period >= arrival_period and ship_present_at(d, ship, period)
    )


@dataclass
class _FeasibleAllocator:
    """Incremental common-constraint decoder used by every literature method.

    Static inventory, temporal-support, compatibility, job, and distance
    indexes are cached here. These indexes only avoid repeated evaluation of
    the same baseline inputs; they do not change a literature method's
    ordering, reward, pricing, or feasibility rules.
    """

    d: dict
    base_occupancy: dict[tuple[str, int], int] = field(default_factory=dict)
    base_heights: dict[tuple[str, int], set[str]] = field(default_factory=dict)
    planned_occupancy: dict[tuple[str, int], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    planned_heights: dict[tuple[str, int], set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    din: dict[tuple[str, str, str, int], int] = field(
        default_factory=lambda: defaultdict(int)
    )
    occupied_period_cache: dict[tuple[str, int], tuple[int, ...]] = field(
        default_factory=dict
    )
    compatible_blocks_cache: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    compatible_bays_cache: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )
    jobs_cache: tuple[Job, ...] = ()
    mean_block_distance: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        attrs = self.d["group_attrs"]
        locked_by_bay: dict[str, list[tuple[str, int]]] = defaultdict(list)
        for (bay, old_ship), quantity in self.d["locked_inventory"].items():
            if quantity > 0:
                locked_by_bay[bay].append((old_ship, int(round(quantity))))
        actual_by_bay: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for (bay, ship, group), quantity in self.d["actual_inventory"].items():
            if quantity > 0:
                actual_by_bay[bay].append(
                    (ship, group, int(round(quantity)))
                )
        for bay in self.d["bays"]:
            for period in self.d["periods"]:
                occupancy = 0
                heights: set[str] = set()
                for old_ship, quantity in locked_by_bay.get(bay, ()):
                    if self.d["locked_release_local"].get(
                        (bay, old_ship), 10**9
                    ) > period:
                        occupancy += quantity
                        height = self.d["locked_height"].get(
                            (bay, old_ship)
                        )
                        if height is not None:
                            heights.add(height)
                for ship, group, quantity in actual_by_bay.get(bay, ()):
                    if ship_present_at(self.d, ship, period):
                        occupancy += quantity
                        heights.add(attrs[group]["height"])
                self.base_occupancy[bay, period] = occupancy
                self.base_heights[bay, period] = heights
        self.jobs_cache = tuple(_jobs(self.d))
        self.mean_block_distance = {
            ship: sum(
                self.d["distance"][ship, block] for block in self.d["blocks"]
            )
            / max(1, len(self.d["blocks"]))
            for ship in self.d["active_ships"]
        }

    def jobs(self) -> tuple[Job, ...]:
        return self.jobs_cache

    def occupied_periods(
        self, ship: str, arrival_period: int
    ) -> tuple[int, ...]:
        key = (ship, arrival_period)
        if key not in self.occupied_period_cache:
            self.occupied_period_cache[key] = _occupied_periods(
                self.d, ship, arrival_period
            )
        return self.occupied_period_cache[key]

    def compatible_bays(self, group: str) -> tuple[str, ...]:
        if group not in self.compatible_bays_cache:
            self.compatible_bays_cache[group] = tuple(
                bay for bay in self.d["bays"] if compatible(self.d, bay, group)
            )
        return self.compatible_bays_cache[group]

    def feasible_quantity(
        self,
        bay: str,
        ship: str,
        group: str,
        arrival_period: int,
    ) -> int:
        if not compatible(self.d, bay, group):
            return 0
        periods = self.occupied_periods(ship, arrival_period)
        if not periods:
            return 0
        height = self.d["group_attrs"][group]["height"]
        residuals: list[int] = []
        for period in periods:
            used_heights = (
                self.base_heights[bay, period]
                | self.planned_heights[bay, period]
            )
            if used_heights and used_heights != {height}:
                return 0
            residuals.append(
                int(
                    math.floor(
                        self.d["capacity"][bay]
                        - self.base_occupancy[bay, period]
                        - self.planned_occupancy[bay, period]
                        + 1e-9
                    )
                )
            )
        return max(0, min(residuals, default=0))

    def take(
        self,
        bay: str,
        ship: str,
        group: str,
        arrival_period: int,
        requested: int,
    ) -> int:
        quantity = min(
            max(0, int(requested)),
            self.feasible_quantity(bay, ship, group, arrival_period),
        )
        if quantity <= 0:
            return 0
        height = self.d["group_attrs"][group]["height"]
        for period in self.occupied_periods(ship, arrival_period):
            self.planned_occupancy[bay, period] += quantity
            self.planned_heights[bay, period].add(height)
        self.din[bay, ship, group, arrival_period] += quantity
        return quantity

    def compatible_blocks(self, group: str) -> tuple[str, ...]:
        if group not in self.compatible_blocks_cache:
            self.compatible_blocks_cache[group] = tuple(
                block
                for block in self.d["blocks"]
                if any(
                    compatible(self.d, bay, group)
                    for bay in self.d["bays_in_block"][block]
                )
            )
        return self.compatible_blocks_cache[group]

    def best_fit_bay(
        self,
        block: str,
        ship: str,
        group: str,
        arrival_period: int,
        remaining: int,
    ) -> tuple[str, int] | None:
        candidates = []
        for bay in self.d["bays_in_block"][block]:
            free = self.feasible_quantity(bay, ship, group, arrival_period)
            if free <= 0:
                continue
            fit = (0, free - remaining) if free >= remaining else (1, -free)
            candidates.append((fit, bay, free))
        if not candidates:
            return None
        _fit, bay, free = min(candidates)
        return bay, free


def _fill_from_ranked_blocks(
    allocator: _FeasibleAllocator,
    *,
    ship: str,
    group: str,
    period: int,
    quantity: int,
    blocks: tuple[str, ...] | list[str],
    deadline: float,
) -> int:
    """Decode a block ordering without invoking any candidate repair."""
    remaining = int(quantity)
    for block in blocks:
        while remaining > 0 and time.perf_counter() < deadline:
            candidate = allocator.best_fit_bay(
                block, ship, group, period, remaining
            )
            if candidate is None:
                break
            bay, _free = candidate
            taken = allocator.take(bay, ship, group, period, remaining)
            if taken <= 0:
                break
            remaining -= taken
        if remaining <= 0 or time.perf_counter() >= deadline:
            break
    return remaining


def _solve_kp_dos(
    d: dict,
    allocator: _FeasibleAllocator,
    *,
    deadline: float,
) -> tuple[dict, dict, dict]:
    shortage: dict[tuple[str, str, int], int] = {}
    processed_jobs = 0
    priority_trace: list[dict] = []
    for period, release, ship, group, quantity in allocator.jobs():
        blocks = tuple(
            sorted(
                allocator.compatible_blocks(group),
                key=lambda block: (d["distance"][ship, block], block),
            )
        )
        remaining = _fill_from_ranked_blocks(
            allocator,
            ship=ship,
            group=group,
            period=period,
            quantity=quantity,
            blocks=blocks,
            deadline=deadline,
        )
        shortage[ship, group, period] = remaining
        processed_jobs += 1
        if len(priority_trace) < 30:
            priority_trace.append({
                "period": period,
                "release": release,
                "ship": ship,
                "group": group,
                "quantity": quantity,
                "shortage": remaining,
                "block_order": list(blocks),
            })
    diagnostics = {
        "ordering": "period_then_increasing_ship_release",
        "processed_jobs": processed_jobs,
        "priority_trace": priority_trace,
    }
    return shortage, diagnostics, {}


def _aggregate_base_occupancy(
    d: dict, allocator: _FeasibleAllocator
) -> tuple[dict[tuple[str, int], int], dict[str, int]]:
    capacity = {
        block: sum(d["capacity"][bay] for bay in d["bays_in_block"][block])
        for block in d["blocks"]
    }
    base = {
        (block, period): sum(
            allocator.base_occupancy[bay, period]
            for bay in d["bays_in_block"][block]
        )
        for block in d["blocks"]
        for period in d["periods"]
    }
    return base, capacity


def _kp_reduced_block_cost(
    d: dict,
    prices: dict[tuple[str, int], float],
    *,
    block: str,
    ship: str,
    arrival_period: int,
    occupied: tuple[int, ...] | None = None,
    mean_distance: float | None = None,
) -> float:
    if mean_distance is None:
        distances = [d["distance"][ship, item] for item in d["blocks"]]
        mean_distance = sum(distances) / max(1, len(distances))
    if occupied is None:
        occupied = _occupied_periods(d, ship, arrival_period)
    price = sum(prices[block, period] for period in occupied)
    return d["distance"][ship, block] / max(1e-9, mean_distance) + price


def _kp_relaxed_assignment(
    d: dict,
    allocator: _FeasibleAllocator,
    prices: dict[tuple[str, int], float],
) -> tuple[dict, dict, float, int]:
    """Solve the adapted vessel subproblems in the source's reverse-stage order."""
    base, capacity = _aggregate_base_occupancy(d, allocator)
    allocation: dict[tuple[str, str, str, int], int] = defaultdict(int)
    load: dict[tuple[str, int], int] = defaultdict(int)
    native_travel_cost = 0.0
    relaxed_shortage = 0
    jobs = allocator.jobs()
    ships = sorted({ship for _period, _release, ship, _group, _qty in jobs})
    for ship in ships:
        local_load: dict[tuple[str, int], int] = defaultdict(int)
        ship_jobs = sorted(
            (job for job in jobs if job[2] == ship),
            key=lambda job: (-job[0], job[3]),
        )
        for period, _release, _ship, group, quantity in ship_jobs:
            occupied = allocator.occupied_periods(ship, period)
            mean_distance = allocator.mean_block_distance[ship]
            blocks = sorted(
                allocator.compatible_blocks(group),
                key=lambda block: (
                    _kp_reduced_block_cost(
                        d,
                        prices,
                        block=block,
                        ship=ship,
                        arrival_period=period,
                        occupied=occupied,
                        mean_distance=mean_distance,
                    ),
                    block,
                ),
            )
            remaining = int(quantity)
            for block in blocks:
                residual = min(
                    (
                        capacity[block]
                        - base[block, occupied_period]
                        - local_load[block, occupied_period]
                        for occupied_period in occupied
                    ),
                    default=0,
                )
                taken = min(remaining, max(0, int(residual)))
                if taken <= 0:
                    continue
                allocation[block, ship, group, period] += taken
                for occupied_period in occupied:
                    local_load[block, occupied_period] += taken
                    load[block, occupied_period] += taken
                native_travel_cost += (
                    taken
                    * d["distance"][ship, block]
                    / max(1e-9, mean_distance)
                )
                remaining -= taken
                if remaining <= 0:
                    break
            relaxed_shortage += remaining
    return allocation, load, native_travel_cost, relaxed_shortage


def _kp_aggregate_dos_upper_bound(
    d: dict,
    allocator: _FeasibleAllocator,
) -> float:
    """Build a source-domain feasible DOS bound before bay-level decoding."""
    base, capacity = _aggregate_base_occupancy(d, allocator)
    load: dict[tuple[str, int], int] = defaultdict(int)
    cost = 0.0
    shortage = 0
    for period, _release, ship, group, quantity in allocator.jobs():
        occupied = allocator.occupied_periods(ship, period)
        mean_distance = allocator.mean_block_distance[ship]
        blocks = sorted(
            allocator.compatible_blocks(group),
            key=lambda block: (
                d["distance"][ship, block] / max(1e-9, mean_distance),
                block,
            ),
        )
        remaining = int(quantity)
        for block in blocks:
            residual = min(
                (
                    capacity[block]
                    - base[block, occupied_period]
                    - load[block, occupied_period]
                    for occupied_period in occupied
                ),
                default=0,
            )
            taken = min(remaining, max(0, int(residual)))
            if taken <= 0:
                continue
            for occupied_period in occupied:
                load[block, occupied_period] += taken
            cost += (
                taken
                * d["distance"][ship, block]
                / max(1e-9, mean_distance)
            )
            remaining -= taken
            if remaining <= 0:
                break
        shortage += remaining
    return cost + KP_SHORTAGE_PENALTY * shortage


def _kp_subgradient_prices(
    d: dict,
    allocator: _FeasibleAllocator,
    *,
    deadline: float,
) -> tuple[
    dict[tuple[str, int], float],
    dict[tuple[str, str, int], tuple[str, ...]],
    dict,
]:
    """Apply the full-text KP relaxation with disclosed step conventions."""
    base, capacity = _aggregate_base_occupancy(d, allocator)
    prices: dict[tuple[str, int], float] = defaultdict(float)
    feasible_upper_bound = _kp_aggregate_dos_upper_bound(d, allocator)
    best_relaxed_score = -math.inf
    best_allocation: dict[tuple[str, str, str, int], int] = {}
    best_prices: dict[tuple[str, int], float] = dict(prices)
    lagrangian_parameter = KP_SG_INITIAL_LAMBDA
    no_improvement = 0
    iterations = 0
    overload_trace: list[float] = []
    relaxed_score_trace: list[float] = []
    lambda_trace: list[float] = []
    stop_reason = "iteration_limit"
    for iteration in range(KP_SG_MAX_ITERATIONS):
        if time.perf_counter() >= deadline:
            stop_reason = "time_limit"
            break
        allocation, load, travel_cost, relaxed_shortage = (
            _kp_relaxed_assignment(d, allocator, prices)
        )
        overloads = {
            (block, period): (
                base[block, period]
                + load[block, period]
                - capacity[block]
            )
            for block in d["blocks"]
            for period in d["periods"]
        }
        max_overload = max(overloads.values(), default=0.0)
        relaxed_score = (
            travel_cost
            + KP_SHORTAGE_PENALTY * relaxed_shortage
            + sum(
                prices[block, period] * overload
                for (block, period), overload in overloads.items()
            )
        )
        overload_trace.append(float(max_overload))
        relaxed_score_trace.append(float(relaxed_score))
        lambda_trace.append(float(lagrangian_parameter))
        iterations = iteration + 1
        if relaxed_score > best_relaxed_score + 1e-9:
            best_relaxed_score = relaxed_score
            best_allocation = dict(allocation)
            best_prices = dict(prices)
            no_improvement = 0
        else:
            no_improvement += 1
        if max_overload <= 1e-9 and relaxed_shortage <= 0:
            stop_reason = "relaxed_solution_feasible"
            break
        norm_squared = sum(value * value for value in overloads.values())
        if norm_squared <= 1e-12:
            stop_reason = "zero_subgradient"
            break
        gap = max(1e-9, feasible_upper_bound - relaxed_score)
        step = lagrangian_parameter * gap / norm_squared
        for (block, period), overload in overloads.items():
            prices[block, period] = max(
                0.0, prices[block, period] + step * overload
            )
        if no_improvement >= KP_SG_NO_IMPROVEMENT_WINDOW:
            lagrangian_parameter *= 0.5
            no_improvement = 0
            if lagrangian_parameter < KP_SG_MIN_LAMBDA:
                stop_reason = "lambda_threshold"
                break

    preferred: dict[tuple[str, str, int], tuple[str, ...]] = {}
    for period, _release, ship, group, _quantity in allocator.jobs():
        allocated = sorted(
            (
                (quantity, block)
                for (block, item_ship, item_group, item_period), quantity
                in best_allocation.items()
                if (
                    item_ship == ship
                    and item_group == group
                    and item_period == period
                    and quantity > 0
                )
            ),
            key=lambda item: (-item[0], item[1]),
        )
        preferred[ship, group, period] = tuple(
            block for _quantity, block in allocated
        )
    diagnostics = {
        "relaxation": "aggregate_block_period_capacity",
        "subproblem_ordering": "per_vessel_reverse_arrival_stage",
        "step_rule": "held_wolfe_upper_bound_gap_over_subgradient_norm",
        "iterations": iterations,
        "stop_reason": stop_reason,
        "initial_lambda": KP_SG_INITIAL_LAMBDA,
        "final_lambda": lagrangian_parameter,
        "no_improvement_window": KP_SG_NO_IMPROVEMENT_WINDOW,
        "minimum_lambda": KP_SG_MIN_LAMBDA,
        "feasible_upper_bound": float(feasible_upper_bound),
        "best_relaxed_score": (
            float(best_relaxed_score)
            if math.isfinite(best_relaxed_score)
            else None
        ),
        "overload_trace": overload_trace[:KP_SG_MAX_ITERATIONS],
        "relaxed_score_trace": relaxed_score_trace[:KP_SG_MAX_ITERATIONS],
        "lambda_trace": lambda_trace[:KP_SG_MAX_ITERATIONS],
        "positive_multiplier_count": sum(
            value > 1e-12 for value in best_prices.values()
        ),
        "max_multiplier": max(best_prices.values(), default=0.0),
        "parameter_provenance": (
            "lambda_0=2_is_standard_convention;"
            "window=5_is_paper_reported_range_lower_endpoint"
        ),
        "feasibility_recovery": (
            "latest_release_priority_via_chronological_decode_then_"
            "least_cost_increase_common_bay_decoder"
        ),
    }
    return defaultdict(float, best_prices), preferred, diagnostics


def _solve_kp_sg(
    d: dict,
    allocator: _FeasibleAllocator,
    *,
    deadline: float,
    start: float,
    time_limit: float,
) -> tuple[dict, dict, dict]:
    pricing_deadline = min(
        deadline,
        start + max(0.0, min(0.5 * time_limit, time_limit - 0.02)),
    )
    prices, preferred, diagnostics = _kp_subgradient_prices(
        d, allocator, deadline=pricing_deadline
    )
    diagnostics["pricing_time"] = time.perf_counter() - start
    shortage: dict[tuple[str, str, int], int] = {}
    block_rankings: list[dict] = []
    for period, release, ship, group, quantity in allocator.jobs():
        occupied = allocator.occupied_periods(ship, period)
        mean_distance = allocator.mean_block_distance[ship]
        reduced_order = tuple(
            sorted(
                allocator.compatible_blocks(group),
                key=lambda block: (
                    _kp_reduced_block_cost(
                        d,
                        prices,
                        block=block,
                        ship=ship,
                        arrival_period=period,
                        occupied=occupied,
                        mean_distance=mean_distance,
                    ),
                    block,
                ),
            )
        )
        preferred_order = preferred.get((ship, group, period), ())
        blocks = tuple(dict.fromkeys((*preferred_order, *reduced_order)))
        remaining = _fill_from_ranked_blocks(
            allocator,
            ship=ship,
            group=group,
            period=period,
            quantity=quantity,
            blocks=blocks,
            deadline=deadline,
        )
        shortage[ship, group, period] = remaining
        if len(block_rankings) < 30:
            block_rankings.append({
                "period": period,
                "release": release,
                "ship": ship,
                "group": group,
                "quantity": quantity,
                "shortage": remaining,
                "block_order": list(blocks),
            })
    diagnostics["block_rankings"] = block_rankings
    return shortage, diagnostics, {}


def _preferred_future_blocks(
    d: dict, allocator: _FeasibleAllocator
) -> dict[tuple[str, str, int], str]:
    result = {}
    for period, _release, ship, group, _quantity in allocator.jobs():
        blocks = allocator.compatible_blocks(group)
        if blocks:
            result[ship, group, period] = min(
                blocks, key=lambda block: (d["distance"][ship, block], block)
            )
    return result


def _dra_reward(
    d: dict,
    allocator: _FeasibleAllocator,
    *,
    bay: str,
    ship: str,
    group: str,
    period: int,
    remaining: int,
    history: dict[tuple[str, str, str], list[float]],
    block_period_pairs: dict[tuple[str, int], set[Pair]],
    preferred_future: dict[tuple[str, str, int], str],
    parameters: dict[str, float] | None = None,
    static_cache: dict | None = None,
    current_free: int | None = None,
    next_quantity: int | None = None,
    future_capacity: int | None = None,
) -> tuple[float, dict[str, float]]:
    parameters = parameters or DRA_PARAMETER_PROFILES["frozen"]
    block = d["bay_block"][bay]
    outbound_peak = (
        static_cache["outbound_peak"]
        if static_cache is not None
        else max(d["forecast_outbound"].values(), default=1)
    )
    outbound = d["forecast_outbound"].get((block, period), 0)
    tau = 10.0 * outbound / max(1, outbound_peak)
    future_outbound_conflict = (
        static_cache["future_outbound_conflict"].get(
            (block, period), False
        )
        if static_cache is not None
        else any(
            future > period and value > 0 and item == block
            for (item, future), value in d["forecast_outbound"].items()
        )
    )
    if tau >= 10.0 - 1e-9:
        conflict_1 = -100.0
    elif tau > 0:
        conflict_1 = -20.0
    elif future_outbound_conflict:
        conflict_1 = 20.0
    else:
        conflict_1 = 100.0

    pair = (ship, group)
    current_other = any(
        item != pair for item in block_period_pairs[block, period]
    )
    future_other = (
        any(
            item != pair
            for item in static_cache["future_pairs"].get(
                (block, period), ()
            )
        )
        if static_cache is not None
        else any(
            (future_ship, future_group) != pair
            and future_period == period + 1
            and preferred_block == block
            for (
                future_ship,
                future_group,
                future_period,
            ), preferred_block in preferred_future.items()
        )
    )
    if current_other:
        conflict_2 = -50.0
    elif future_other:
        conflict_2 = -20.0
    else:
        conflict_2 = 0.0

    if static_cache is not None:
        mean_distance = static_cache["mean_distance"][ship]
    else:
        distances = [d["distance"][ship, item] for item in d["blocks"]]
        mean_distance = sum(distances) / max(1, len(distances))
    distance_score = 20.0 - (
        d["distance"][ship, block] / max(1e-9, mean_distance) * 20.0
    )

    free = (
        allocator.feasible_quantity(bay, ship, group, period)
        if current_free is None
        else current_free
    )
    space_score = (
        -(free - remaining) / free * 10.0
        if free > remaining and free > 0
        else 0.0
    )

    past_values = history.get((ship, group, block), [])
    past_score = sum(
        parameters["history_discount"] ** (len(past_values) - index) * value
        for index, value in enumerate(past_values)
    )

    if next_quantity is None:
        next_quantity = int(
            round(d["forecast_arrivals"].get((ship, group, period + 1), 0))
        )
    if next_quantity <= 0:
        future_score = 0.0
    else:
        if future_capacity is None:
            future_capacity = max(
                (
                    allocator.feasible_quantity(
                        item, ship, group, period + 1
                    )
                    for item in d["bays_in_block"][block]
                ),
                default=0,
            )
        future_score = (
            (future_capacity - next_quantity)
            / max(1, future_capacity)
            * 10.0
            if future_capacity >= next_quantity
            else -10.0
        )
    conflict = conflict_1 + conflict_2
    reward = (
        conflict
        + distance_score
        + space_score
        + parameters["mu"] * past_score
        + parameters["nu"] * future_score
    )
    return reward, {
        "conflict_1": conflict_1,
        "conflict_2": conflict_2,
        "conflict": conflict,
        "distance": distance_score,
        "space": space_score,
        "past": past_score,
        "future": future_score,
        "total": reward,
    }


def _solve_dra_rpm(
    d: dict,
    allocator: _FeasibleAllocator,
    *,
    deadline: float,
    method_state: dict | None,
    parameters: dict[str, float],
) -> tuple[dict, dict, dict]:
    incoming_history = (method_state or {}).get("reward_history", {})
    history: dict[tuple[str, str, str], list[float]] = {
        tuple(key): [float(value) for value in values]
        for key, values in incoming_history.items()
    }
    block_period_pairs: dict[tuple[str, int], set[Pair]] = defaultdict(set)
    preferred_future = _preferred_future_blocks(d, allocator)
    future_pairs: dict[tuple[str, int], set[Pair]] = defaultdict(set)
    for (ship, group, future_period), block in preferred_future.items():
        future_pairs[block, future_period - 1].add((ship, group))
    positive_outbound_periods: dict[str, tuple[int, ...]] = {
        block: tuple(
            sorted(
                period
                for (item, period), value in d[
                    "forecast_outbound"
                ].items()
                if item == block and value > 0
            )
        )
        for block in d["blocks"]
    }
    static_cache = {
        "outbound_peak": max(d["forecast_outbound"].values(), default=1),
        "future_outbound_conflict": {
            (block, period): any(
                future > period
                for future in positive_outbound_periods[block]
            )
            for block in d["blocks"]
            for period in d["periods"]
        },
        "future_pairs": future_pairs,
        "mean_distance": dict(allocator.mean_block_distance),
        "compatible_bays": {
            group: allocator.compatible_bays(group)
            for group in d["group_attrs"]
        },
    }
    shortage: dict[tuple[str, str, int], int] = {}
    decisions: list[dict] = []
    reward_total = 0.0
    for period, _release, ship, group, quantity in allocator.jobs():
        remaining = quantity
        if time.perf_counter() >= deadline:
            shortage[ship, group, period] = remaining
            continue
        compatible_bays = static_cache["compatible_bays"][group]
        free_by_bay: dict[str, int] = {}
        initialization_complete = True
        for bay in compatible_bays:
            if time.perf_counter() >= deadline:
                initialization_complete = False
                break
            free_by_bay[bay] = allocator.feasible_quantity(
                bay, ship, group, period
            )
        if not initialization_complete:
            shortage[ship, group, period] = remaining
            continue
        next_quantity = int(
            round(
                d["forecast_arrivals"].get(
                    (ship, group, period + 1), 0
                )
            )
        )
        future_free_by_bay: dict[str, int] = {}
        future_capacity_by_block: dict[str, int] = {}
        if next_quantity > 0:
            for bay in compatible_bays:
                if time.perf_counter() >= deadline:
                    initialization_complete = False
                    break
                future_free_by_bay[bay] = allocator.feasible_quantity(
                    bay, ship, group, period + 1
                )
            if not initialization_complete:
                shortage[ship, group, period] = remaining
                continue
            future_capacity_by_block = {
                block: max(
                    (
                        future_free_by_bay.get(item, 0)
                        for item in d["bays_in_block"][block]
                    ),
                    default=0,
                )
                for block in d["blocks"]
            }
        while remaining > 0 and time.perf_counter() < deadline:
            candidates = []
            for bay in compatible_bays:
                if time.perf_counter() >= deadline:
                    break
                free = free_by_bay[bay]
                if free <= 0:
                    continue
                block = d["bay_block"][bay]
                reward, components = _dra_reward(
                    d,
                    allocator,
                    bay=bay,
                    ship=ship,
                    group=group,
                    period=period,
                    remaining=remaining,
                    history=history,
                    block_period_pairs=block_period_pairs,
                    preferred_future=preferred_future,
                    parameters=parameters,
                    static_cache=static_cache,
                    current_free=free,
                    next_quantity=next_quantity,
                    future_capacity=(
                        future_capacity_by_block.get(block)
                        if next_quantity > 0
                        else None
                    ),
                )
                fit = (
                    (0, free - remaining)
                    if free >= remaining
                    else (1, -free)
                )
                candidates.append((
                    (
                        -reward,
                        d["distance"][ship, block],
                        fit[0],
                        fit[1],
                        bay,
                    ),
                    bay,
                    reward,
                    components,
                ))
            if time.perf_counter() >= deadline:
                break
            if not candidates:
                break
            _rank, bay, reward, reward_components = min(candidates)
            taken = allocator.take(bay, ship, group, period, remaining)
            if taken <= 0:
                break
            block = d["bay_block"][bay]
            free_by_bay[bay] = allocator.feasible_quantity(
                bay, ship, group, period
            )
            if next_quantity > 0:
                future_free_by_bay[bay] = allocator.feasible_quantity(
                    bay, ship, group, period + 1
                )
                future_capacity_by_block[block] = max(
                    (
                        future_free_by_bay.get(item, 0)
                        for item in d["bays_in_block"][block]
                    ),
                    default=0,
                )
            remaining -= taken
            reward_total += reward
            block_period_pairs[block, period].add((ship, group))
            values = history.setdefault((ship, group, block), [])
            values.append(float(reward))
            del values[:-DRA_HISTORY_LIMIT]
            if len(decisions) < 100:
                decisions.append({
                    "period": period,
                    "ship": ship,
                    "group": group,
                    "bay": bay,
                    "block": block,
                    "quantity": taken,
                    "reward": reward_components,
                })
        shortage[ship, group, period] = remaining
    diagnostics = {
        "reward_choice": "maximize_equation_27",
        "mu": parameters["mu"],
        "nu": parameters["nu"],
        "history_discount": parameters["history_discount"],
        "native_reward_total": reward_total,
        "decision_count": sum(
            1 for quantity in allocator.din.values() if quantity > 0
        ),
        "decisions": decisions,
    }
    next_state = {"reward_history": history}
    return shortage, diagnostics, next_state


def _build_common_solution(
    d: dict,
    allocator: _FeasibleAllocator,
    shortage_values: dict[tuple[str, str, int], int],
    *,
    operation_weights: Mapping[str, float] | None = None,
) -> tuple[dict, dict]:
    din = {
        key: int(value)
        for key, value in sorted(allocator.din.items())
        if value > 0
    }
    reservation: dict[tuple[str, str, str], int] = defaultdict(int)
    for (bay, ship, group, _period), quantity in din.items():
        reservation[bay, ship, group] += quantity
    reservation = {
        key: int(value)
        for key, value in sorted(reservation.items())
        if value > 0
    }
    shortage = {
        (ship, group, period): int(
            shortage_values.get((ship, group, period), 0)
        )
        for ship, group in sorted(d["remaining_demand"])
        for period in d["periods"]
    }
    inventory = {}
    for bay, ship, group in reservation:
        for period in d["periods"]:
            cumulative = sum(
                quantity
                for (
                    item_bay,
                    item_ship,
                    item_group,
                    arrival,
                ), quantity in din.items()
                if (
                    item_bay == bay
                    and item_ship == ship
                    and item_group == group
                    and arrival <= period
                )
            )
            inventory[bay, ship, group, period] = (
                int(
                    round(
                        d["actual_inventory"].get(
                            (bay, ship, group), 0
                        )
                    )
                )
                + cumulative
                if ship_present_at(d, ship, period)
                else 0
            )

    canonical = canonical_stability_metrics(d, reservation, shortage)
    scales = compute_objective_scales(d)
    attrs = d["group_attrs"]
    concentration_raw = float(
        len({
            (ship, attrs[group]["pod"], bay)
            for (bay, ship, group), quantity in reservation.items()
            if quantity > 0
        })
    )
    occupancy_balance_raw = 0.0
    for period in d["periods"]:
        utilizations = []
        for block in d["blocks"]:
            block_capacity = sum(
                d["capacity"][bay]
                for bay in d["bays_in_block"][block]
            )
            occupancy = sum(
                allocator.base_occupancy[bay, period]
                + allocator.planned_occupancy[bay, period]
                for bay in d["bays_in_block"][block]
            )
            utilizations.append(occupancy / max(1, block_capacity))
        average = sum(utilizations) / max(1, len(utilizations))
        occupancy_balance_raw += sum(
            abs(value - average) for value in utilizations
        )
    distance_raw = float(
        sum(
            d["distance"][ship, d["bay_block"][bay]] * quantity
            for (bay, ship, _group, _period), quantity in din.items()
        )
    )
    peak = max(d["forecast_outbound"].values(), default=1)
    conflict_raw = float(
        sum(
            d["forecast_outbound"].get(
                (d["bay_block"][bay], period), 0
            )
            / max(1, peak)
            * quantity
            for (bay, _ship, _group, period), quantity in din.items()
        )
    )
    concentration_normalized = (
        concentration_raw / scales["concentration_scale"]
    )
    balance_normalized = (
        occupancy_balance_raw / scales["occupancy_balance_scale"]
    )
    distance_normalized = distance_raw / scales["distance_scale"]
    conflict_normalized = (
        conflict_raw / scales["in_out_conflict_scale"]
    )
    weights = resolve_operation_weights(operation_weights)
    concentration_weighted = weights["concentration"] * concentration_normalized
    occupancy_balance_weighted = weights["balance"] * balance_normalized
    distance_weighted = weights["distance"] * distance_normalized
    conflict_weighted = weights["in_out_conflict"] * conflict_normalized
    normalized_operations_score = (
        concentration_weighted
        + occupancy_balance_weighted
        + distance_weighted
        + conflict_weighted
    )
    components = {
        "predicted_shortage": float(sum(shortage.values())),
        **{
            key: canonical[key]
            for key in (
                "cancellation_quantity",
                "mandatory_reduction",
                "discretionary_cancel",
                "new_bay_count",
                "block_reallocation_quantity",
                "stability_cost",
            )
        },
        "concentration_raw": concentration_raw,
        "occupancy_balance_raw": occupancy_balance_raw,
        "distance_raw": distance_raw,
        "in_out_conflict_raw": conflict_raw,
        "concentration_normalized": concentration_normalized,
        "occupancy_balance_normalized": balance_normalized,
        "distance_normalized": distance_normalized,
        "in_out_conflict_normalized": conflict_normalized,
        "concentration_weight": weights["concentration"],
        "occupancy_balance_weight": weights["balance"],
        "distance_weight": weights["distance"],
        "in_out_conflict_weight": weights["in_out_conflict"],
        "concentration_weighted": concentration_weighted,
        "occupancy_balance_weighted": occupancy_balance_weighted,
        "distance_weighted": distance_weighted,
        "in_out_conflict_weighted": conflict_weighted,
        "normalized_operations_score": normalized_operations_score,
        **{name: float(value) for name, value in scales.items()},
    }
    solution = {
        "reservation": reservation,
        "din": din,
        "inventory": inventory,
        "shortage": shortage,
        "pair_cancellation": canonical["pair_cancellation"],
        "pair_discretionary_cancel": canonical[
            "pair_discretionary_cancel"
        ],
        "block_reallocation": canonical["pair_block_reallocation"],
        "components": components,
    }
    return solution, scales


def solve_literature_baseline(
    d: dict,
    *,
    configuration: str,
    time_limit: float = 60,
    seed: int = 0,
    method_state: dict | None = None,
    parameter_profile: str = "frozen",
    operation_weights: Mapping[str, float] | None = None,
) -> dict:
    """Solve one visible snapshot using an adapted published heuristic."""
    del seed  # All three frozen adaptations use deterministic tie-breaking.
    if configuration not in LITERATURE_CONFIGURATIONS:
        raise ValueError(
            f"configuration must be one of {LITERATURE_CONFIGURATIONS}"
        )
    if parameter_profile not in DRA_PARAMETER_PROFILES:
        raise ValueError(
            "parameter_profile must be one of "
            f"{tuple(DRA_PARAMETER_PROFILES)}"
        )
    started = time.perf_counter()
    limit = max(0.0, float(time_limit))
    postprocessing_reserve = postprocessing_reserve_seconds(limit)
    deadline = started + max(0.0, limit - postprocessing_reserve)
    allocator = _FeasibleAllocator(d)
    preprocessing_time = 0.0
    solver: Callable
    if configuration == "kp_dos":
        solver = lambda: _solve_kp_dos(
            d, allocator, deadline=deadline
        )
    elif configuration == "kp_sg":
        solver = lambda: _solve_kp_sg(
            d,
            allocator,
            deadline=deadline,
            start=started,
            time_limit=max(0.0, float(time_limit)),
        )
    else:
        solver = lambda: _solve_dra_rpm(
            d,
            allocator,
            deadline=deadline,
            method_state=method_state,
            parameters=DRA_PARAMETER_PROFILES[parameter_profile],
        )
    shortage, diagnostics, next_method_state = solver()
    if configuration == "kp_sg":
        preprocessing_time = float(diagnostics.get("pricing_time", 0.0))
    search_time = time.perf_counter() - started
    extract_started = time.perf_counter()
    solution, scales = _build_common_solution(
        d,
        allocator,
        shortage,
        operation_weights=operation_weights,
    )
    solution_extract_time = time.perf_counter() - extract_started
    online_decision_time = time.perf_counter() - started
    validation_started = time.perf_counter()
    validation = validate_rolling_solution(d, solution)
    validation_time = time.perf_counter() - validation_started
    audit_wall_time = time.perf_counter() - started
    deadline_exceeded = (
        online_decision_time
        > max(0.0, float(time_limit)) + WALL_TIME_TOLERANCE_SECONDS
    )
    optimization_budget_binding = (
        online_decision_time
        >= max(0.0, limit - postprocessing_reserve) - .01
    )
    failure_status = None
    if deadline_exceeded:
        failure_status = "online_decision_time_limit_exceeded"
    elif not validation["feasible"]:
        failure_status = "solution_validation_failed"
    if not validation["feasible"]:
        termination_status = "VALIDATION_FAILED"
    elif deadline_exceeded:
        termination_status = "DEADLINE_MISS"
    elif optimization_budget_binding:
        termination_status = "TIME_LIMIT_FEASIBLE"
    else:
        termination_status = "FEASIBLE"
    spec = BASELINE_SPECS[configuration]
    stage = {
        "stage": configuration,
        "baseline_family": spec["family"],
        "baseline_method": spec["method"],
        "baseline_fidelity": spec["fidelity"],
        "status": termination_status,
        "runtime": search_time,
        "solver_runtime": 0.0,
        "model_build_time": 0.0,
        "stage_wall_time": online_decision_time,
        "first_incumbent_time": search_time,
        "stage_first_incumbent_time": search_time,
        "nodes": 0.0,
        "variables": 0,
        "binary_variables": 0,
        "constraints": 0,
        "has_solution": True,
        "solution_count": 1,
        "objective_bound": None,
        "mip_gap": None,
        "native_objective_direction": spec["native_direction"],
        "baseline_diagnostics": diagnostics,
    }
    return {
        "ok": validation["feasible"] and not deadline_exceeded,
        "failure_status": failure_status,
        "termination_status": termination_status,
        "decision_deadline_met": not deadline_exceeded,
        "optimization_budget_binding": optimization_budget_binding,
        "configuration": configuration,
        "solution": solution,
        "validation": validation,
        "baseline_diagnostics": diagnostics,
        "baseline_metadata": baseline_row_metadata(
            configuration, parameter_profile
        ),
        "method_state": next_method_state,
        "affected_ships": list(d["active_ships"]),
        "impact_diagnostics": {
            "propagated_pairs": [],
            "pressure_propagation": [],
            "release_opportunity_propagation": [],
            "dependency_edge_count": 0,
        },
        "stability_budget_diagnostics": {
            "previous_reservation": float(
                sum(d["previous_reservation"].values())
            ),
            "baseline_has_stability_budget": False,
        },
        "objective_scales": scales,
        "stages": [stage],
        "repair_triggered": False,
        "repair_expansions": 0,
        "bottleneck_repair_triggered": False,
        "bottleneck_selected_pair_block_count": 0,
        "quality_polish_triggered": False,
        "quality_polish_improved": False,
        "preprocessing_time": preprocessing_time,
        "direct_impact_time": 0.0,
        "objective_scale_time": 0.0,
        "dependency_graph_time": 0.0,
        "candidate_ranking_time": 0.0,
        "bottleneck_selection_time": 0.0,
        "model_build_time": 0.0,
        "solver_time": 0.0,
        "algorithm_search_time": search_time,
        "solution_extract_time": solution_extract_time,
        "model_dispose_time": 0.0,
        "final_model_dispose_time": 0.0,
        "validation_time": validation_time,
        "online_decision_time": online_decision_time,
        "audit_wall_time": audit_wall_time,
        "total_wall_time": audit_wall_time,
        "runtime": online_decision_time,
        "wall_time_limit": float(time_limit),
        "wall_time_tolerance": WALL_TIME_TOLERANCE_SECONDS,
        "postprocessing_time_reserve": postprocessing_reserve,
        "final_stage": configuration,
        "cycle_first_incumbent_wall_time": search_time,
        "final_predicted_shortage": solution["components"][
            "predicted_shortage"
        ],
        "final_stability_cost": solution["components"]["stability_cost"],
        "final_normalized_operations_score": solution["components"][
            "normalized_operations_score"
        ],
        "final_stage_objective_bound": None,
        "final_stage_mip_gap": None,
        "stability_formulation": "common_ex_post_accounting",
    }

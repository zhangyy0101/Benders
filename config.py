"""Protocol and algorithm constants for reproducible rolling experiments."""

# These identifiers are written to every formal-format artifact.  Change them
# whenever the mathematical protocol, core algorithm, or output schema changes.
PROBLEM_PROTOCOL = "rolling-v4.6-objective-only-stability"
ALGORITHM_VERSION = "lead-aware-aggregate-lp-residual-global-repair-v1.7.3"
RESULT_SCHEMA_VERSION = "rolling-results-v16"
ONLINE_RUNTIME_PROTOCOL = "strict-online-decision-wall-v1"
FORMAL_ORCHESTRATION_PROTOCOL = "immutable-indexed-publication-v2"
FORMAL_CORE_CONFIGURATION = "full_bottleneck"
EXTERNAL_BASELINE_PROTOCOL = "adapted-literature-baselines-v1.1-sparse-cached"
PREPROCESSING_IMPLEMENTATION = "lead-aware-aggregate-lp-sparse-indexed-v5"
PACKING_ORACLE_PROTOCOL = "full-horizon-integer-packing-v2"
SYNTHETIC_PRESSURE_PROTOCOL = (
    "aggregate-size-period-target-integer-certified-v1"
)

# Development and preflight seeds may guide algorithm changes.  Formal seeds
# are a held-out set and must not be used for tuning before the final freeze.
DEVELOPMENT_SEEDS = (100, 101, 102)
PREFLIGHT_SEEDS = (700, 701, 702)
FORMAL_SEEDS = tuple(range(1000, 1010))
# Version 1.6.0 was defined after outputs for FORMAL_SEEDS existed.  Keep formal
# execution closed until a new untouched confirmatory set is registered.
FORMAL_RESULT_AUTHORIZED = False

# Synthetic formal panels separate computational size, initial yard
# utilization, and capacity pressure.  The pressure targets are peak
# full-horizon load ratios over each container-size capacity pool; every
# generated case is still certified by the independent integer bay-packing
# oracle before it can enter a formal instance index.
FORMAL_SYNTHETIC_PRESSURE_TARGETS = {
    "ordinary": 0.70,
    "high_pressure": 0.85,
}
FORMAL_SYNTHETIC_PRESSURE_TARGET_TOLERANCE = 0.03
FORMAL_SYNTHETIC_SCALE_INITIAL_UTILIZATION = 0.55
FORMAL_SYNTHETIC_UTILIZATION_LEVELS = (0.25, 0.55, 0.65)
FORMAL_SYNTHETIC_UTILIZATION_SIZE = "medium"
FORMAL_SYNTHETIC_UTILIZATION_SHIP_VOLUME_FACTOR = 1.0

# Frozen publication matrix.  The online limit is applied independently to
# every 24-hour rolling decision cycle.  Instance bundles carry one of these
# values so a formal runner cannot silently give one method a different budget.
FORMAL_PRIMARY_CONFIGURATIONS = (
    "core_start",
    "full_bottleneck",
    "kp_dos",
    "kp_sg",
    "dra_rpm",
)
FORMAL_TIME_BUDGETS_SECONDS = {
    "pilot_small": 20.0,
    "small": 20.0,
    "medium": 20.0,
    "large": 60.0,
    "xlarge": 120.0,
    "public_small": 20.0,
    "public_medium": 60.0,
    "public_large": 120.0,
    "public_temporal_spring": 60.0,
    "public_temporal_summer": 60.0,
    "public_temporal_autumn": 60.0,
    "pressure": 20.0,
}

# Gurobi's TimeLimit is a solver-work boundary: the optimizer may need
# additional wall time to finalize attributes after the limit is reached.
# Request termination before the online optimization deadline so that this
# solver-return tail and incumbent extraction remain inside the declared
# end-to-end decision budget.
# The frozen 616k--738k variable diagnostics observed at most 1.25 seconds
# between requested termination and a returned model. Keep a two-second guard
# at the 60-second publication budget so multi-objective presolve can finish.
SOLVER_RETURN_GUARD_RATIO = 1 / 30
SOLVER_RETURN_GUARD_MIN_SECONDS = .25
SOLVER_RETURN_GUARD_MAX_SECONDS = 12.0
GLOBAL_CORE_MIP_FOCUS = 1
GLOBAL_CORE_HEURISTICS = .20
GLOBAL_CORE_START_NODE_LIMIT = 2000
# A bottleneck repair starts only after an incumbent exposes shortage. Reserve
# enough of the unchanged online window to build the unrestricted safety MIP,
# and do not launch it when the remaining build window is implausibly short.
# These are controller allocations, not a separate runtime allowance.
GLOBAL_REPAIR_RESERVE_RATIO = .25
GLOBAL_REPAIR_RESERVE_MIN_SECONDS = .50
GLOBAL_REPAIR_RESERVE_MAX_SECONDS = 20.0
GLOBAL_REPAIR_MIN_START_SECONDS = .05
GLOBAL_REPAIR_MIN_START_RATIO = 1 / 6
GLOBAL_REPAIR_MIN_START_MAX_SECONDS = 10.0
FORMAL_PUBLIC_WINDOWS = {
    "public_small": {
        "start_date": "2025-07-04",
        "end_date": "2025-07-06",
        "num_blocks": 8,
        "bays_per_block": 6,
        "bay_capacity": 50,
    },
    "public_medium": {
        "start_date": "2025-07-12",
        "end_date": "2025-07-18",
        "num_blocks": 16,
        "bays_per_block": 8,
        "bay_capacity": 50,
    },
    "public_large": {
        "start_date": "2025-07-20",
        "end_date": "2025-07-30",
        "num_blocks": 20,
        "bays_per_block": 10,
        "bay_capacity": 50,
    },
}
# These equal-layout, equal-duration windows are a separate temporal
# robustness panel.  They must be generated from the matching independently
# archived monthly source/calibration directory and must not be pooled with the
# three July scale profiles.
FORMAL_PUBLIC_TEMPORAL_WINDOWS = {
    "public_temporal_spring": {
        "start_date": "2025-03-12",
        "end_date": "2025-03-18",
        "num_blocks": 16,
        "bays_per_block": 8,
        "bay_capacity": 50,
    },
    "public_temporal_summer": {
        "start_date": "2025-07-12",
        "end_date": "2025-07-18",
        "num_blocks": 16,
        "bays_per_block": 8,
        "bay_capacity": 50,
    },
    "public_temporal_autumn": {
        "start_date": "2025-11-12",
        "end_date": "2025-11-18",
        "num_blocks": 16,
        "bays_per_block": 8,
        "bay_capacity": 50,
    },
}
FORMAL_PUBLIC_CALIBRATION_BASE = {
    "design_capacity_teu_per_year": 2_236_000,
    "capacity_utilization": 0.85,
    "import_export_split_to_export": 0.50,
    "forty_foot_box_share": 0.65,
    "high_cube_share_of_forty": 0.55,
    "min_boxes_per_call": 80,
    "max_boxes_per_call": 450,
    "boxes_per_pod": 100,
    "max_pods_per_call": 12,
}
FORMAL_PUBLIC_CALIBRATION_SCENARIOS = {
    "central": dict(FORMAL_PUBLIC_CALIBRATION_BASE),
    "utilization_low": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "capacity_utilization": 0.70,
    },
    "utilization_high": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "capacity_utilization": 1.00,
    },
    "export_split_low": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "import_export_split_to_export": 0.45,
    },
    "export_split_high": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "import_export_split_to_export": 0.55,
    },
    "forty_share_low": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "forty_foot_box_share": 0.55,
    },
    "forty_share_high": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "forty_foot_box_share": 0.75,
    },
    "high_cube_low": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "high_cube_share_of_forty": 0.40,
    },
    "high_cube_high": {
        **FORMAL_PUBLIC_CALIBRATION_BASE,
        "high_cube_share_of_forty": 0.70,
    },
}
ROLLING_CYCLE_HOURS=24
RECEIVING_WINDOW_HOURS=72
TIME_BUCKET_HOURS=6
LOOKAHEAD_HOURS=96
ADMISSION_LEAD_BAND_HOURS=(72,96)
DEFAULT_IMPACT_THRESHOLD=.10
DEFAULT_OUTBOUND_BOXES_PER_6H=150
INITIAL_BAY_MAX_FILL_RATIO=.95
INITIAL_UTILIZATION_TOLERANCE=1e-9
FORECAST_ERROR_MODES=(
    "multiplicative",
    "timing_shift",
    "booking_add_cancel",
    "ship_correlated",
    "mixed",
)
FORECAST_ERROR_CORRELATION=.70
FORECAST_MIN_SIGMA_RATIO=.05
SHIP_OPERATION_DURATION_RANGES={
    "small":(1,2),
    "medium":(2,3),
    "large":(3,4),
}
WALL_TIME_TOLERANCE_SECONDS=.20
# Sparse incumbent extraction and single-pass canonical accounting keep the
# large-instance post-solver tail near three seconds in the frozen runtime
# diagnostic. Retain a 4.2-second tail at the 60-second publication budget.
POSTPROCESSING_RESERVE_RATIO=.07
POSTPROCESSING_RESERVE_MIN_SECONDS=.50
POSTPROCESSING_RESERVE_MAX_SECONDS=20.0
VALIDATE_EACH_EXECUTION_PERIOD=True
USE_EXACT_STABILITY_BIG_M=False

STABILITY_CANCEL_WEIGHT=1.0
STABILITY_NEW_BAY_WEIGHT=10.0
STABILITY_BLOCK_REALLOCATION_WEIGHT=1.0

OPERATION_OBJECTIVE_NORMALIZATION = "reachable_snapshot_upper_bounds_v2"
OPERATION_WEIGHT_PROFILE = "business"
OPERATION_WEIGHT_PROFILES = {
    "equal_weight_ablation": {
        "concentration": .25,
        "balance": .25,
        "distance": .25,
        "in_out_conflict": .25,
    },
    "weak": {
        "concentration": .225,
        "balance": .275,
        "distance": .325,
        "in_out_conflict": .175,
    },
    "business": {
        "concentration": .20,
        "balance": .30,
        "distance": .40,
        "in_out_conflict": .10,
    },
    "strong_distance": {
        "concentration": .15,
        "balance": .25,
        "distance": .55,
        "in_out_conflict": .05,
    },
}
OPERATION_WEIGHT_CONCENTRATION = OPERATION_WEIGHT_PROFILES[
    OPERATION_WEIGHT_PROFILE
]["concentration"]
OPERATION_WEIGHT_BALANCE = OPERATION_WEIGHT_PROFILES[
    OPERATION_WEIGHT_PROFILE
]["balance"]
OPERATION_WEIGHT_DISTANCE = OPERATION_WEIGHT_PROFILES[
    OPERATION_WEIGHT_PROFILE
]["distance"]
OPERATION_WEIGHT_IN_OUT_CONFLICT = OPERATION_WEIGHT_PROFILES[
    OPERATION_WEIGHT_PROFILE
]["in_out_conflict"]

ADAPTIVE_BLOCK_BATCH_RATIO=.20
ADAPTIVE_GLOBAL_BYPASS_ENABLED=True
# Bypass the restricted repair path only when both a horizon-wide load measure
# and a current free-capacity measure indicate severe pressure.  These tests use
# snapshot state rather than instance-size labels.
ADAPTIVE_GLOBAL_PEAK_LOAD_THRESHOLD=.80
ADAPTIVE_GLOBAL_DEMAND_FREE_CAPACITY_THRESHOLD=1.0
AGGREGATE_DOMAIN_LADDER_ENABLED=True
AGGREGATE_DOMAIN_LADDER_BUDGET_RATIO=.05
AGGREGATE_DOMAIN_LADDER_MAX_SECONDS=1.0
AGGREGATE_DOMAIN_LADDER_LEVELS=(0,1,2)
# The declared forecast-error magnitude is combined with the maximum visible
# lead-time sigma and used as a conservative screening buffer. It is not
# presented as a probabilistic confidence radius.
AGGREGATE_DOMAIN_LADDER_BUFFER_MULTIPLIER=1.0
BOTTLENECK_SELECTOR_BUDGET_RATIO=.05
BOTTLENECK_SELECTOR_MAX_SECONDS=1.0
QUALITY_POLISH_ENABLED=False
QUALITY_POLISH_PAIR_RATIO=.50
QUALITY_POLISH_BLOCKS_PER_PAIR=2
QUALITY_POLISH_WEIGHT_SUPPORT=1.0
QUALITY_POLISH_WEIGHT_DISTANCE=1.0
QUALITY_POLISH_WEIGHT_OVERLAP=1.0
QUALITY_POLISH_WEIGHT_UTILIZATION=1.0
IMPACT_SCORE_CAPACITY_WEIGHT=5.0
IMPACT_SCORE_DISTANCE_WEIGHT=1.25
IMPACT_SCORE_OUTBOUND_WEIGHT=1.25
IMPACT_SCORE_BALANCE_WEIGHT=1.0
IMPACT_SCORE_BAY_WEIGHT=.75
IMPACT_SCORE_STABILITY_WEIGHT=2.0
TIME_CAPACITY_WEIGHT=.70
MINIMUM_PERIOD_CAPACITY_WEIGHT=.30

DEPENDENCY_PROPAGATION_ENABLED=True
DEPENDENCY_TRIGGER_MODE="shortage_repair_only"
DEPENDENCY_CANDIDATE_BLOCK_RATIO=.30
DEPENDENCY_EDGE_THRESHOLD=.35
DEPENDENCY_PATH_THRESHOLD=.20
DEPENDENCY_PROFILES={
    "conservative":{"edge_threshold":.50,"path_threshold":.35},
    "current":{"edge_threshold":DEPENDENCY_EDGE_THRESHOLD,"path_threshold":DEPENDENCY_PATH_THRESHOLD},
    "expansive":{"edge_threshold":.20,"path_threshold":.10},
}
DEPENDENCY_MAX_DEPTH=2
DEPENDENCY_DECAY=.85
DEPENDENCY_MAX_NEIGHBORS_PER_PAIR=8
DEPENDENCY_WEIGHT_CANDIDATE_OVERLAP=.35
DEPENDENCY_WEIGHT_TEMPORAL_OVERLAP=.25
DEPENDENCY_WEIGHT_CAPACITY_PRESSURE=.25
DEPENDENCY_WEIGHT_HISTORICAL_OVERLAP=.15

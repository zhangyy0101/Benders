"""Protocol and algorithm constants for reproducible rolling experiments."""

# These identifiers are written to every formal-format artifact.  Change them
# whenever the mathematical protocol, core algorithm, or output schema changes.
PROBLEM_PROTOCOL = "rolling-v4.3-oracle-certified"
ALGORITHM_VERSION = "lead-aware-aggregate-lp-screened-repair-v1.3"
RESULT_SCHEMA_VERSION = "rolling-results-v7"
FORMAL_CORE_CONFIGURATION = "full_bottleneck"
EXTERNAL_BASELINE_PROTOCOL = "adapted-literature-baselines-v1"
PREPROCESSING_IMPLEMENTATION = "lead-aware-aggregate-lp-sparse-indexed-v3"
PACKING_ORACLE_PROTOCOL = "full-horizon-integer-packing-v1"

# Development and preflight seeds may guide algorithm changes.  Formal seeds
# are a held-out set and must not be used for tuning before the final freeze.
DEVELOPMENT_SEEDS = (100, 101, 102)
PREFLIGHT_SEEDS = (700, 701, 702)
FORMAL_SEEDS = tuple(range(1000, 1010))

# Frozen publication matrix.  The online limit is applied independently to
# every 24-hour rolling decision cycle.  Instance bundles carry one of these
# values so a formal runner cannot silently give one method a different budget.
FORMAL_PRIMARY_CONFIGURATIONS = (
    "core",
    "core_start",
    "core_start_impact",
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
POSTPROCESSING_RESERVE_RATIO=.15
POSTPROCESSING_RESERVE_MIN_SECONDS=.50
POSTPROCESSING_RESERVE_MAX_SECONDS=10.0
VALIDATE_EACH_EXECUTION_PERIOD=True
USE_EXACT_STABILITY_BIG_M=False

STABILITY_CANCEL_WEIGHT=1.0
STABILITY_NEW_BAY_WEIGHT=10.0
STABILITY_BLOCK_REALLOCATION_WEIGHT=1.0
STABILITY_BASE_RATIO=.10
STABILITY_CHANGE_RATIO=.50

OPERATION_OBJECTIVE_NORMALIZATION = "unrestricted_snapshot_scales"
OPERATION_WEIGHT_CONCENTRATION=1.0
OPERATION_WEIGHT_BALANCE=1.0
OPERATION_WEIGHT_DISTANCE=1.0
OPERATION_WEIGHT_IN_OUT_CONFLICT=1.0

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

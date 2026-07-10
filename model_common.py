"""Shared, deterministic data and objective helpers for Route A."""
from solver_bbc import (  # migrated compatibility layer; no callback is used
    _arrival as arrival,
    _attribute_score as attribute_score,
    _attribute_values as attribute_values,
    _compute_old_occupancy as compute_old_occupancy,
    _fixed_in_block as fixed_in_block,
    _group_attr as group_attr,
    _group_size as group_size,
    _master_raw_components_from_fix as raw_components,
    _new_groups as new_groups,
    _objective_scale_factor as objective_scale_factor,
    _objective_scales as objective_scales,
    _outbound_pressure as outbound_pressure,
)


"""Frozen on-disk schema declarations for yard benchmark instances."""
from __future__ import annotations

SCHEMA_VERSION = "yard-bay-instance-v1"
PROBLEM_PROTOCOL = "paper-exp-v1"
TOP_LEVEL_FIELDS = {"schema_version", "problem_protocol", "instance_id", "digest", "instance_state", "data"}

# Field-specific tuple-key schemas. The final record column is always ``value``.
RECORD_SCHEMAS = {
    "Dist": ("ship", "block"),
    "initial_inventory_data": ("bay", "old_ship", "size"),
    "Arrivals_interval": ("new_ship", "size", "period"),
    "Arrivals_group_interval": ("new_ship", "group", "period"),
    "Block_Outbound_Vol": ("block", "period"),
    "Block_Outbound_Req": ("block", "old_ship", "period"),
    "Fixed_In_Flow": ("old_ship", "size", "bay", "period"),
    "Fixed_Mode_Force": ("bay", "period"),
    "Fixed_Bay_Mode": ("bay",),
    "Old_Box_Occupancy_Map": ("bay", "old_ship"),
    "Old_Ship_Size_Map": ("bay", "old_ship"),
    "Bay_Handling_Rate": ("bay", "period"),
}

PREPARED_ONLY_FIELDS = {
    "handling_rate_base", "handling_rate_scale", "handling_rate_source",
    "old_outbound_release_policy",
}

ALGORITHM_CONFIGURATION_FIELDS = {
    "algorithm_configuration", "candidate_algorithm_defaults", "configuration_hash",
    "configuration_name", "algorithm_family",
}

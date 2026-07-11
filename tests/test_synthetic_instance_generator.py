import copy
import random

import pytest

from data import get_data_3new6old_fixed, prepare_instance, simulate_old_inventory, validate_instance_units
from model_concentration import has_joint_attribute_groups
from synthetic_instance_generator import SyntheticInstanceSpec, generate_synthetic_instance


def spec(**changes):
    values = dict(
        name="generator_test", num_blocks=3, bays_per_block=4,
        bay_capacity_boxes=50.0, num_berths=2, num_new_ships=2,
        num_old_ships=2, num_periods=5, time_bucket_hours=6.0, alpha=1.1,
        handling_rate_boxes_per_hour=25.0, initial_utilization_range=(.10, .20),
        fixed_inbound_ratio_range=(.02, .08), outbound_pressure_ratio_range=(.10, .25),
        arrival_boxes_per_ship_range=(40.0, 60.0), arrival_overlap_level=.7,
        peak_position_range=(.4, .6), mode_20ft_share=.5, group_profile="standard",
    )
    values.update(changes)
    return SyntheticInstanceSpec(**values)


def test_same_seed_is_identical_and_different_seed_changes_core_data():
    first = generate_synthetic_instance(spec(), 17)
    assert first == generate_synthetic_instance(spec(), 17)
    second = generate_synthetic_instance(spec(), 18)
    assert first["Arrivals_interval"] != second["Arrivals_interval"]
    assert first["benchmark_metadata"]["seed"] == 17


def test_generator_does_not_pollute_global_random_state():
    random.seed(991)
    expected = [random.random() for _ in range(4)]
    random.seed(991)
    generate_synthetic_instance(spec(), 4)
    actual = [random.random() for _ in range(4)]
    assert actual == expected


def test_generated_instance_is_complete_and_physically_valid():
    data = generate_synthetic_instance(spec(), 9)
    validate_instance_units(data)
    prepared = prepare_instance(data)
    validate_instance_units(prepared)
    assert has_joint_attribute_groups(data)
    simulation = simulate_old_inventory(data)
    assert simulation["max_capacity_violation"] <= 1e-9
    assert max(simulation["unserved_outbound"].values(), default=0) <= 1e-9
    assert max(data["Block_Outbound_Vol"].values()) > 0
    assert len(set(data["Block_Outbound_Vol"].values())) > 1
    for j in data["J_new"]:
        for size in data["S"]:
            matching = [g for g in data["G"] if data["GroupSize"][g] == size]
            for n in data["N"]:
                assert sum(data["Arrivals_group_interval"][j, g, n] for g in matching) == pytest.approx(data["Arrivals_interval"][j, size, n])


def test_names_support_more_than_26_blocks():
    data = generate_synthetic_instance(spec(num_blocks=27, bays_per_block=2, arrival_boxes_per_ship_range=(5.0, 8.0)), 3)
    assert data["K"][-1] == "Block_027"
    assert "Bay_027_002" in data["I"]


@pytest.mark.parametrize("change,match", [
    ({"initial_utilization_range": (.8, .2)}, "initial_utilization_range"),
    ({"arrival_overlap_level": 1.2}, "arrival_overlap_level"),
    ({"group_profile": "unknown"}, "group_profile"),
    ({"num_periods": 0}, "num_periods"),
])
def test_invalid_specs_are_rejected(change, match):
    with pytest.raises(ValueError, match=match):
        generate_synthetic_instance(spec(**change), 1)


def test_capacity_insufficient_spec_is_rejected_with_diagnostics():
    tight = spec(
        num_blocks=1, bays_per_block=2, bay_capacity_boxes=10,
        initial_utilization_range=(.8, .8), fixed_inbound_ratio_range=(0, 0),
        arrival_boxes_per_ship_range=(100, 100),
    )
    with pytest.raises(ValueError, match="compatible reserve capacity insufficient.*demand=.*capacity="):
        generate_synthetic_instance(tight, 1)


def test_legacy_3new6old_is_unchanged_by_generator_calls():
    before = copy.deepcopy(get_data_3new6old_fixed())
    generate_synthetic_instance(spec(), 22)
    assert get_data_3new6old_fixed() == before

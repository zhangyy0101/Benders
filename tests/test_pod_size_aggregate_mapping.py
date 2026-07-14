from instance_registry import build_builtin_instance
from data import prepare_instance
from model_aggregate_recourse_lb import active_ship_pod_sizes, groups_for_ship_pod_size
from model_common import group_attr, group_size, ship_groups


def test_active_pod_size_partition_exactly_covers_ship_groups():
    data = prepare_instance(build_builtin_instance("tiny_concentration"))
    triples = active_ship_pod_sizes(data)
    for ship in data["J_new"]:
        covered = []
        for j, pod, size in triples:
            if j == ship:
                groups = groups_for_ship_pod_size(data, ship, pod, size)
                assert all(group_attr(data, g, "pod") == pod and group_size(data, g) == size for g in groups)
                covered.extend(groups)
        assert sorted(covered) == sorted(ship_groups(data, ship))
        assert len(covered) == len(set(covered))

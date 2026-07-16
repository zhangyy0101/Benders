"""Canonical JSON IO, digesting, comparison, and inspection for raw benchmarks."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA_VERSION="yard-bay-instance-v1";PROBLEM_PROTOCOL="paper-exp-v1";TOP_LEVEL_FIELDS={"schema_version","problem_protocol","instance_id","digest","instance_state","data"}
RECORD_SCHEMAS={"Dist":("ship","block"),"initial_inventory_data":("bay","old_ship","size"),"Arrivals_interval":("new_ship","size","period"),"Arrivals_group_interval":("new_ship","group","period"),"Block_Outbound_Vol":("block","period"),"Block_Outbound_Req":("block","old_ship","period"),"Fixed_In_Flow":("old_ship","size","bay","period"),"Fixed_Mode_Force":("bay","period"),"Fixed_Bay_Mode":("bay",),"Old_Box_Occupancy_Map":("bay","old_ship"),"Old_Ship_Size_Map":("bay","old_ship"),"OldBayHeight":("bay",)}
PREPARED_ONLY_FIELDS={"old_outbound_release_policy"}
ALGORITHM_CONFIGURATION_FIELDS={"algorithm_configuration","candidate_algorithm_defaults","configuration_hash","configuration_name","algorithm_family"}


def _encoded_value(value):
    if isinstance(value, tuple):
        return {"__tuple__": [_encoded_value(item) for item in value]}
    if isinstance(value, list):
        return [_encoded_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("unregistered dictionary with non-string keys")
        return {key: _encoded_value(value[key]) for key in sorted(value)}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("benchmark values must be finite")
        return value
    raise TypeError(f"unsupported benchmark value type: {type(value).__name__}")


def _decoded_value(value):
    if isinstance(value, list):
        return [_decoded_value(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"__tuple__"}:
            if not isinstance(value["__tuple__"], list):
                raise ValueError("invalid tuple encoding")
            return tuple(_decoded_value(item) for item in value["__tuple__"])
        if "__tuple__" in value:
            raise ValueError("reserved __tuple__ key mixed with ordinary fields")
        return {key: _decoded_value(item) for key, item in value.items()}
    return value


def _record_sort_key(record):
    return json.dumps(record[:-1], sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_instance_data(instance):
    if not isinstance(instance, dict) or not all(isinstance(key, str) for key in instance):
        raise TypeError("instance must be a string-keyed dictionary")
    forbidden = sorted(ALGORITHM_CONFIGURATION_FIELDS.intersection(instance))
    if forbidden:
        raise ValueError(f"algorithm configuration is not instance data: {forbidden}")
    encoded = {}
    for field in sorted(instance):
        value = instance[field]
        if field in RECORD_SCHEMAS:
            if not isinstance(value, dict):
                raise TypeError(f"{field} must be a dictionary")
            columns = RECORD_SCHEMAS[field]
            records = []
            for key, item in value.items():
                key_tuple = key if isinstance(key, tuple) else (key,)
                if len(key_tuple) != len(columns):
                    raise ValueError(f"{field} key {key!r} does not match columns {columns}")
                records.append([*(_encoded_value(part) for part in key_tuple), _encoded_value(item)])
            records.sort(key=_record_sort_key)
            encoded[field] = {"record_schema": field, "columns": [*columns, "value"], "records": records}
        else:
            encoded[field] = _encoded_value(value)
    return encoded


def canonical_instance_payload(instance):
    """Return the stable payload covered by the instance digest."""
    return {"schema_version": SCHEMA_VERSION, "problem_protocol": PROBLEM_PROTOCOL, "instance_state": "raw", "data": canonical_instance_data(instance)}


def instance_digest(instance):
    text = json.dumps(canonical_instance_payload(instance), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _assert_raw(instance):
    present = sorted(PREPARED_ONLY_FIELDS.intersection(instance))
    if present:
        raise ValueError(f"only raw instances may be saved; prepared fields present: {present}")


def save_instance(instance, path, *, instance_id=None):
    _assert_raw(instance)
    target = Path(path)
    identifier = instance_id or str(instance.get("ScenarioName") or target.stem)
    document = {**canonical_instance_payload(instance), "instance_id": identifier, "digest": instance_digest(instance)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {key: document[key] for key in ("schema_version", "problem_protocol", "instance_id", "digest", "instance_state")}


def _decode_data(encoded):
    if not isinstance(encoded, dict):
        raise ValueError("benchmark data must be an object")
    result = {}
    for field, value in encoded.items():
        if field in RECORD_SCHEMAS:
            expected_columns = [*RECORD_SCHEMAS[field], "value"]
            if not isinstance(value, dict) or set(value) != {"record_schema", "columns", "records"}:
                raise ValueError(f"invalid record wrapper for {field}")
            if value["record_schema"] != field or value["columns"] != expected_columns or not isinstance(value["records"], list):
                raise ValueError(f"record schema mismatch for {field}")
            mapping = {}
            for record in value["records"]:
                if not isinstance(record, list) or len(record) != len(expected_columns):
                    raise ValueError(f"invalid {field} record: {record!r}")
                parts = tuple(_decoded_value(part) for part in record[:-1])
                key = parts[0] if len(parts) == 1 else parts
                if key in mapping:
                    raise ValueError(f"duplicate {field} key: {key!r}")
                mapping[key] = _decoded_value(record[-1])
            result[field] = mapping
        else:
            result[field] = _decoded_value(value)
    return result


def load_instance(path, *, verify_digest=True):
    source = Path(path)
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != TOP_LEVEL_FIELDS:
        extra = sorted(set(document) - TOP_LEVEL_FIELDS) if isinstance(document, dict) else []
        missing = sorted(TOP_LEVEL_FIELDS - set(document)) if isinstance(document, dict) else sorted(TOP_LEVEL_FIELDS)
        raise ValueError(f"invalid benchmark top-level fields; missing={missing}, extra={extra}")
    if document["schema_version"] != SCHEMA_VERSION or document["problem_protocol"] != PROBLEM_PROTOCOL or document["instance_state"] != "raw":
        raise ValueError("unsupported benchmark schema, protocol, or instance state")
    instance = _decode_data(document["data"])
    _assert_raw(instance)
    actual = instance_digest(instance)
    if verify_digest and document["digest"] != actual:
        raise ValueError(f"benchmark digest mismatch: stored={document['digest']}, actual={actual}")
    return instance


def compare_instances(left, right, tolerance=1e-9):
    differences = []
    def compare(a, b, path):
        if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
            if abs(float(a) - float(b)) > tolerance:
                differences.append({"path": path, "left": a, "right": b})
        elif type(a) is not type(b):
            differences.append({"path": path, "left_type": type(a).__name__, "right_type": type(b).__name__})
        elif isinstance(a, dict):
            for key in sorted(set(a) | set(b), key=repr):
                if key not in a or key not in b:
                    differences.append({"path": f"{path}[{key!r}]", "missing_from": "left" if key not in a else "right"})
                else: compare(a[key], b[key], f"{path}[{key!r}]")
        elif isinstance(a, (list, tuple)):
            if len(a) != len(b): differences.append({"path": path, "left_length": len(a), "right_length": len(b)})
            for index, (x, y) in enumerate(zip(a, b)): compare(x, y, f"{path}[{index}]")
        elif a != b:
            differences.append({"path": path, "left": a, "right": b})
    compare(left, right, "data")
    return {"equal": not differences, "difference_count": len(differences), "differences": differences}


def inspect_instance(path):
    from data import prepare_instance, simulate_old_inventory
    from model_concentration import has_joint_attribute_groups
    raw = load_instance(path)
    identifier = json.loads(Path(path).read_text(encoding="utf-8"))["instance_id"]
    prepared = prepare_instance(raw)
    simulation = simulate_old_inventory(prepared)
    capacity = sum(float(prepared["I"][i]["cap"]) for i in prepared["I_list"])
    initial = sum(float(value) for value in prepared["initial_inventory_data"].values())
    return {
        "instance_id": identifier, "digest": instance_digest(raw),
        "schema_version": SCHEMA_VERSION, "problem_protocol": PROBLEM_PROTOCOL,
        "dimensions": {"blocks": len(raw["K"]), "bays": len(raw["I_list"]), "new_ships": len(raw["J_new"]), "old_ships": len(raw["J_old"]), "periods": len(raw["N"]), "groups": len(raw.get("G", []))},
        "total_arrivals": sum(float(value) for value in raw["Arrivals_interval"].values()),
        "initial_utilization": initial / capacity if capacity else None,
        "concentration_available": has_joint_attribute_groups(prepared),
        "validation": {"ok": True, "old_capacity_violation": simulation["max_capacity_violation"], "max_unserved_outbound": max(simulation["unserved_outbound"].values(), default=0)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("inspect", "verify"))
    parser.add_argument("path")
    args = parser.parse_args()
    report = inspect_instance(args.path)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

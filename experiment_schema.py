"""Result-schema validation and stable identity construction."""
from __future__ import annotations
import hashlib,json
SCHEMA_VERSION="experiment-result-v1"
REQUIRED=("schema_version","run_id","identity","configuration","status","timing","optimization","evaluation","environment")
def stable_run_id(payload):return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def validate_result(result):
    missing=[key for key in REQUIRED if key not in result]
    if missing:raise ValueError(f"experiment result missing fields: {missing}")
    if result["schema_version"]!=SCHEMA_VERSION:raise ValueError("experiment result schema mismatch")
    if result["status"].get("ok") and not result.get("evaluation"):raise ValueError("successful result requires common evaluation")
    if result.get("status",{}).get("status")!="EXCEPTION":
        trace=result.get("anytime_trace")
        if trace is None:raise ValueError("non-exception result requires anytime_trace")
        for key in ("time_to_first_feasible","time_to_best","primal_integral","gap_integral"):
            if key not in result["optimization"]:raise ValueError(f"optimization missing anytime metric {key}")
    return result

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_candidate_status_files_agree():
    status = json.loads((ROOT / "docs/pilot21_status.json").read_text(encoding="utf-8"))
    decision = json.loads((ROOT / "algorithm_candidate_decision.json").read_text(encoding="utf-8"))
    for key in ("candidate_algorithm_frozen", "candidate_configuration", "final_algorithm_frozen", "approved_for_public_data_pilot"):
        assert status[key] == decision[key]
        assert status[key] == status["p4_candidate_freeze_review"][key]


def test_public_data_authorization_wording_is_consistent():
    plan = (ROOT / "docs/PUBLIC_DATA_PILOT_PLAN.md").read_text(encoding="utf-8")
    assert "P4 authorizes development/calibration-set adaptation and testing" in plan
    assert "does not authorize final holdout execution" in plan
    assert "P4 does not authorize public-data adaptation" not in plan

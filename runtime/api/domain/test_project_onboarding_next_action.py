"""Setup selection follows required facts and the live activation fact."""

from pathlib import Path

import pytest
from yoke_contracts.onboard_checklist import ROW_SPECS, REQUIRED_SETUP_ROW_IDS
from yoke_core.domain.project_onboarding_next_action import select_next_action


def rows():
    return [
        {
            "row_id": s.row_id,
            "title": s.title,
            "layer": s.layer,
            "status": "configured",
            "reason": "",
            "recovery": "",
        }
        for s in ROW_SPECS
    ]


@pytest.mark.parametrize("status", ["unknown", "needed", "blocked", "deferred"])
def test_required_recovery_precedes_activation(status):
    facts = rows()
    facts[0].update(
        status=status, reason="missing_package", recovery="yoke setup --agent"
    )
    action = select_next_action(facts, {"ready": False})
    assert action["row_id"] == facts[0]["row_id"]
    assert action["command"] == "yoke setup --agent"
    assert action["reason"] == "missing_package"


def test_optional_rows_never_force_setup_and_first_work_uses_its_fact():
    facts = rows()
    for row in facts:
        if row["row_id"] not in REQUIRED_SETUP_ROW_IDS:
            row["status"] = "unknown"
        if row["row_id"] == "lifecycle-readiness":
            row.update(
                reason="first_item_not_done", recovery="Run /yoke steer CURRENT-PLAN"
            )
    action = select_next_action(facts, {"ready": True})
    assert action["row_id"] == "lifecycle-readiness"
    assert action["command"] == "Run /yoke steer CURRENT-PLAN"
    next(row for row in facts if row["row_id"] == "lifecycle-readiness")["status"] = (
        "verified"
    )
    assert select_next_action(facts, {"ready": True}) is None


def test_each_result_has_an_installed_home():
    root = Path(__file__).resolve().parents[3]
    for row in rows():
        if row["row_id"] not in REQUIRED_SETUP_ROW_IDS:
            continue
        row.update(status="unknown", recovery="/yoke onboard")
        action = select_next_action([row], {"ready": False})
        assert (root / action["home"]).is_file()

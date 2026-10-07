"""Pinned Refine closure owns acceptance criteria; floor Tasks are exempt."""

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.idea_readiness_check import run_all_checks
from yoke_core.domain.idea_readiness_acceptance_criteria import (
    verify_refine_acceptance_criteria,
)
from yoke_core.engines import advance_implementation_preflight_gates as gates
from yoke_contracts.api.function_call import FunctionCallResponse


@pytest.mark.parametrize(
    "spec, missing",
    [("No criteria", True), ("## Acceptance Criteria\n- [ ] observable result", False)],
)
def test_issue_closure_uses_shared_presence_check(spec, missing):
    with test_database() as conn:
        item_id = 9700
        insert_item(conn, id=item_id, status="refining-idea", spec=spec)
        issues = run_all_checks(conn, item_id).issues
        ac_issues = [
            issue for issue in issues if issue.code == "MISSING_ACCEPTANCE_CRITERIA"
        ]
        assert bool(ac_issues) is missing
        if missing:
            assert "PRD-9" in ac_issues[0].message
            assert f"YOK-{item_id}" in ac_issues[0].message
            assert "rerun yoke readiness check" in ac_issues[0].remediation


def test_idea_time_authoring_is_not_blocked_by_missing_criteria():
    with test_database() as conn:
        item_id = 9701
        insert_item(conn, id=item_id, status="idea", spec="No criteria")
        assert verify_refine_acceptance_criteria(conn, item_id, "No criteria") == []


def test_pinned_task_without_refine_binding_has_no_criteria_obligation():
    with test_database() as conn:
        item_id = 9703
        insert_item(
            conn,
            id=item_id,
            status="implementing",
            workflow_id="task",
            spec="No criteria",
        )
        assert verify_refine_acceptance_criteria(conn, item_id, "No criteria") == []


@pytest.mark.parametrize(
    "workflow, policy", [("task", "optional"), ("issue", "required")]
)
def test_entry_does_not_repeat_refine_criteria_check(monkeypatch, workflow, policy):
    calls = []
    results = {
        "advance.preflight.hard_blocks": {"blockers": []},
        "workflows.item.get": {
            "workflow_id": workflow,
            "effective_policies": {"file_budget": policy},
        },
        "advance.preflight.file_budget": {"verdict": "pass"},
        "advance.preflight.spec_coverage": {"is_blocked": False},
    }

    def relay(**kwargs):
        calls.append(kwargs["function_id"])
        return FunctionCallResponse(
            success=True,
            function=kwargs["function_id"],
            version="v1",
            result=results[kwargs["function_id"]],
        )

    monkeypatch.setattr(gates, "call_dispatcher", relay)
    assert gates._run_preflight_gates("ITEM-9702", force=False) == (True, "")
    assert all("ac_presence" not in call for call in calls)
    if workflow == "task":
        assert calls == ["advance.preflight.hard_blocks", "workflows.item.get"]

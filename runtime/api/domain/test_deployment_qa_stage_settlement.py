"""Scoped QA writes settle their run gate and reach the existing driver."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_settlement import (
    continuation_message,
    settle_execution,
    settle_subject,
)
from yoke_core.domain.deployment_qa_stage_wake import run_stage_wait_message
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def test_completed_execution_opens_required_human_review_without_redrive(test_db):
    reviewer = 9877
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (reviewer,),
    )
    plan_id = _plan(test_db, "settlement-human-smoke")
    stages = _stages(
        plan_id,
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id="run-settlement-human", stages=stages, members=())
    materialize_deployment_qa_stage(
        test_db, deployment_run_id="run-settlement-human", deployment_stage="item-qa"
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-settlement-human",
        deployment_stage="item-qa",
        actor_id="2",
        session_id="run-qa",
    )
    _complete_case(test_db, execution)
    requests = test_db.execute(
        "SELECT id,status FROM decision_requests "
        "WHERE kind='qa_needs_review' AND status='pending'"
    ).fetchall()
    assert len(requests) == 1
    assert (
        test_db.execute(
            "SELECT current_stage FROM deployment_runs WHERE id=%s",
            ("run-settlement-human",),
        ).fetchone()[0]
        == "item-qa"
    )


@pytest.mark.parametrize("action", ["approve", "waive", "reject"])
def test_item_review_decision_reaches_the_run_driver(test_db, action):
    reviewer = 9888
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (reviewer,),
    )
    plan_id = _plan(test_db, f"item-settlement-{action}")
    stages = _stages(
        plan_id,
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [reviewer]},
        },
    )
    run_id = f"run-item-settlement-{action}"
    member = {"approve": 9881, "waive": 9882, "reject": 9883}[action]
    _seed_run(test_db, run_id=run_id, stages=stages, members=(member,))
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="member-qa",
    )
    _complete_case(test_db, execution)
    request_id = int(
        test_db.execute(
            "SELECT id FROM decision_requests "
            "WHERE kind='qa_needs_review' AND status='pending'"
        ).fetchone()[0]
    )
    with mock.patch(
        "yoke_core.domain.deployment_run_driver_notice.push_run_scoped_notice",
        return_value="delivered",
    ) as notify_driver:
        resolve_decision_request(
            test_db,
            request_id,
            actor_id=reviewer,
            action=action,
            note=f"Reviewed {action} for the frozen target.",
        )
    notify_driver.assert_called_once()
    assert run_id in notify_driver.call_args.kwargs["idempotency_key"]
    assert "item-qa" in notify_driver.call_args.kwargs["idempotency_key"]


def test_settlement_rejects_execution_for_a_different_frozen_target(monkeypatch):
    subject = {"stage": {"name": "visual-qa"}}
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_contract.deployment_qa_stage_subject",
        lambda *args, **kwargs: subject,
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_execution_target.deployment_qa_execution_target",
        lambda *args: {"kind": "run_preview", "revision": "new"},
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_execution_environment_target.target_digest",
        lambda *args: "expected",
    )
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "status": "executing",
        "current_stage": "visual-qa",
    }
    with pytest.raises(ValueError, match="different deployment candidate"):
        settle_execution(
            conn,
            {
                "id": "execution-old",
                "state": "completed",
                "deployment_run_id": "run-frozen",
                "deployment_stage": "visual-qa",
                "execution_target_digest": "old",
            },
        )


def test_replayed_completion_after_stage_advance_does_not_reopen_gate():
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "status": "executing",
        "current_stage": "complete",
    }
    assert (
        settle_execution(
            conn,
            {
                "id": "completed-qa",
                "state": "completed",
                "deployment_run_id": "run-frozen",
                "deployment_stage": "visual-qa",
            },
        )
        is None
    )
    conn.execute.assert_called_once()


def test_item_verdict_requests_same_run_driver_once_per_outcome(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
        lambda *args, **kwargs: {
            "accepted": True,
            "outcome": "passed",
            "target_digest": "frozen-target",
        },
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_qa_stage_settlement.status_project_id",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        "yoke_core.domain.project_identity.resolve_project",
        lambda *args: SimpleNamespace(id=1, slug="yoke"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_driver_notice.push_run_scoped_notice",
        lambda *args, **kwargs: calls.append(kwargs) or "delivered",
    )
    conn = mock.Mock()
    for _ in range(2):
        settle_subject(conn, run_id="run-frozen", stage="item-qa", member=42)
    assert len(calls) == 2
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    assert "run-frozen" in calls[0]["body_for_route"]("driver")
    assert "watch deploy -- run-frozen" in calls[0]["body_for_route"]("driver")


def test_run_visual_wait_assigns_inspection_to_driver():
    message = run_stage_wait_message(
        run_id="run-visual",
        stage_name="visual-qa",
        target_tier="persistent",
        revision="a" * 40,
        reasons="cases not selected",
        route="driver",
        names_cases=False,
    )
    assert "deploy driver owns this run-scoped inspection" in message
    assert "assign a capable QA agent through Yoke" in message
    assert "yoke watch qa-plan -- --deployment-run-id run-visual" in message
    assert "--plan PLAN" in message
    assert "--member" not in message


def test_continuation_keeps_existing_run_and_lock():
    message = continuation_message(
        run_id="run-existing",
        stage="item-qa",
        outcome="passed",
        project_slug="yoke",
        route="driver",
    )
    assert "Continue this same run" in message
    assert "watch deploy -- run-existing" in message

"""Carried item authority settles before a release's shared human gate."""

from __future__ import annotations

from unittest import mock
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_run_gates import (
    RUN_ID,
    _seed_run_awaiting_approval,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_run_gates import run_gates
from yoke_core.domain.deployment_run_history_read import read_deployment_run_history
from yoke_core.domain.deployment_run_list_read import list_deployment_runs
from yoke_core.domain.deployment_run_member_approvals import (
    member_approval_blockers,
    resume_after_member_decision,
)
from yoke_core.domain import deployment_run_auto_completion


def _mixed_run(
    conn, *, posture: str = '{"approval_on_done":true}'
) -> tuple[str, int, int, int]:
    create_decision_request_tables(conn)
    yoke_owner, other_actor = _seed_run_awaiting_approval(conn)
    run_id = "run-mixed-item-decision"
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,flow,target_tier,target_environment_id,release_lineage,"
        "status,current_stage,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,current_stage,created_at "
        "FROM deployment_runs WHERE id=%s",
        (run_id, RUN_ID),
    )
    platform_id = int(conn.execute("SELECT MAX(id)+1 FROM projects").fetchone()[0])
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix,org_id,created_at) "
        "SELECT %s,'platform','Platform','PLAT',org_id,'2026-09-28T00:00:00Z' "
        "FROM projects WHERE id=1",
        (platform_id,),
    )
    owner_role = int(
        conn.execute("SELECT id FROM roles WHERE name='owner'").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO actor_project_roles(actor_id,project_id,role_id,granted_at) "
        "VALUES (%s,%s,%s,'2026-09-28T00:00:00Z')",
        (yoke_owner, platform_id, owner_role),
    )
    version = int(
        conn.execute(
            "SELECT current_version_id FROM workflows WHERE id='dash'"
        ).fetchone()[0]
    )
    item_id = int(
        conn.execute(
            "INSERT INTO items(title,status,priority,created_at,updated_at,source,"
            "owner,project_id,project_sequence,workflow_id,workflow_version_id,"
            "workflow_posture) VALUES ('Platform release member','release','medium',"
            "'2026-09-28T00:00:00Z','2026-09-28T00:00:00Z',%s,%s,%s,1,"
            "'dash',%s,%s) RETURNING id",
            (str(other_actor), str(yoke_owner), platform_id, version, posture),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,delivery_intent,added_at) "
        "VALUES (%s,%s,'final','2026-09-28T00:00:00Z')",
        (run_id, item_id),
    )
    conn.commit()
    return run_id, item_id, yoke_owner, platform_id


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_member_decision_precedes_shared_approval_and_keeps_its_project(
    test_db,
    action,
):
    run_id, item_id, platform_owner, platform_id = _mixed_run(test_db)
    first = evaluate_deployment_stage_approval(
        test_db, run_id=run_id, stage="approve-prod"
    )
    assert first.request_status == "blocked_member"
    assert "PLAT-" in first.reason
    assert "decision request" in first.reason
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
            (f"{run_id}:approve-prod",),
        ).fetchone()[0]
        == 0
    )
    gate = run_gates(test_db, [run_id], actor_id=platform_owner)[run_id][0]
    assert gate["kind"] == "lifecycle_transition_approval"
    assert gate["can_act"] is True
    assert gate["subject_context"]["item_id"] == item_id
    assert gate["subject_context"]["item_ref"].startswith("PLAT-")
    assert (
        test_db.execute(
            "SELECT project_id FROM decision_requests WHERE id=%s",
            (gate["request_id"],),
        ).fetchone()[0]
        == platform_id
    )

    resolve_decision_request(
        test_db,
        gate["request_id"],
        actor_id=platform_owner,
        action=action,
        note="Reviewed the carried item evidence.",
    )
    resolved = run_gates(test_db, [run_id], actor_id=platform_owner)[run_id][0]
    assert resolved["status"] == "resolved"
    assert resolved["resolution_action"] == action
    assert resolved["subject_context"]["item_id"] == item_id
    shared = test_db.execute(
        "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
        (f"{run_id}:approve-prod",),
    ).fetchone()[0]
    if action == "approve":
        assert shared == 1
    else:
        assert shared == 0
        refusal = evaluate_deployment_stage_approval(
            test_db, run_id=run_id, stage="approve-prod"
        )
        assert refusal.request_status == "rejected_member"
        assert str(gate["request_id"]) in refusal.reason
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
            (f"{item_id}:done",),
        ).fetchone()[0]
        == 1
    )


def test_member_without_approval_does_not_delay_shared_request(test_db):
    run_id, _item_id, _owner, _platform_id = _mixed_run(test_db, posture="{}")
    verdict = evaluate_deployment_stage_approval(
        test_db, run_id=run_id, stage="approve-prod"
    )
    assert verdict.request_status == "pending"
    assert verdict.request_id > 0
    assert member_approval_blockers(test_db, run_id) == []


def test_resolved_member_revisits_completed_run_without_driver(test_db, monkeypatch):
    run_id, item_id, owner, _platform_id = _mixed_run(test_db)
    blocked = evaluate_deployment_stage_approval(
        test_db, run_id=run_id, stage="approve-prod"
    )
    assert blocked.request_status == "blocked_member"
    request_id = run_gates(test_db, [run_id], actor_id=owner)[run_id][0]["request_id"]
    test_db.execute(
        "UPDATE decision_requests SET status='resolved',resolution_action='approve',"
        "resolution_actor_id=%s,resolved_at='2026-09-28T00:01:00Z' WHERE id=%s",
        (owner, request_id),
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='complete' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    from yoke_core.domain import deployment_run_auto_completion

    complete = mock.Mock()
    monkeypatch.setattr(
        deployment_run_auto_completion, "continue_after_settlement", complete
    )
    resume_after_member_decision(test_db, item_id)
    complete.assert_called_once_with(test_db, run_id)


def test_project_selection_includes_mixed_run_with_all_members(test_db):
    run_id, platform_item, _owner, platform_id = _mixed_run(test_db)
    version = int(
        test_db.execute(
            "SELECT current_version_id FROM workflows WHERE id='issue'"
        ).fetchone()[0]
    )
    sequence = int(
        test_db.execute(
            "SELECT COALESCE(MAX(project_sequence),0)+1 FROM items WHERE project_id=1"
        ).fetchone()[0]
    )
    yoke_item = int(
        test_db.execute(
            "INSERT INTO items(title,status,priority,created_at,updated_at,source,"
            "owner,project_id,project_sequence,workflow_id,workflow_version_id) "
            "VALUES ('Yoke release member','release','medium','2026-09-28T00:00:00Z',"
            "'2026-09-28T00:00:00Z','2','2',1,%s,'issue',%s) RETURNING id",
            (sequence, version),
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,delivery_intent,added_at) "
        "VALUES (%s,%s,'final','2026-09-28T00:00:00Z')",
        (run_id, yoke_item),
    )
    test_db.commit()
    for selected in (1, platform_id):
        history = read_deployment_run_history(
            test_db,
            project_ids=[selected],
            search=None,
            status=None,
            environment=None,
            flow=None,
            page_size=50,
            cursor=None,
            actor_id=None,
        )
        row = next(row for row in history["rows"] if row["id"] == run_id)
        assert {item["id"] for item in row["member_items"]} == {
            yoke_item,
            platform_item,
        }
    shipping = next(
        row
        for row in list_deployment_runs(
            project="platform", status=None, limit=50, relevance="overview"
        )
        if row["id"] == run_id
    )
    assert {item["id"] for item in shipping["member_items"]} == {
        yoke_item,
        platform_item,
    }


def test_finalization_replays_status_after_last_member_closed(monkeypatch):
    conn = mock.Mock()
    monkeypatch.setattr(
        deployment_run_auto_completion,
        "_readiness",
        lambda *_: ({"remaining": [], "members": [], "delivered_to": "prod"}, ""),
    )
    from yoke_core.domain import (
        deployment_run_collective_finalization,
        deployment_runs_crud_mutate,
    )

    monkeypatch.setattr(
        deployment_run_collective_finalization, "_required_open_members", lambda *_: []
    )
    update = mock.Mock(side_effect=["settlement interrupted", None])
    monkeypatch.setattr(deployment_runs_crud_mutate, "cmd_update", update)
    result = deployment_run_auto_completion.finish_ready_run(conn, "run-settling")
    assert result.completed is True
    assert update.call_count == 2


def test_completed_run_can_close_while_driver_attachment_is_live(monkeypatch):
    from yoke_core.domain import (
        coordination_claims,
        deployment_run_completion_preconditions,
        deployment_run_driver_attachment,
        project_identity,
    )

    monkeypatch.setattr(coordination_claims, "active_claim", lambda *_: None)
    monkeypatch.setattr(
        deployment_run_driver_attachment,
        "live_attachment_for_run",
        lambda *_, **__: SimpleNamespace(session_id="attached-driver"),
    )
    monkeypatch.setattr(
        deployment_run_completion_preconditions,
        "unresolved_blocking_qa",
        lambda *_: [],
    )
    monkeypatch.setattr(
        project_identity, "resolve_project", lambda *_: SimpleNamespace(slug="yoke")
    )
    conn = mock.Mock()
    conn.execute.return_value.fetchone.return_value = {
        "project_id": 1,
        "status": "executing",
        "current_stage": "complete",
        "target_tier": "production",
        "target_name": "prod",
        "stages": '[{"name":"build","step_runner":"auto"}]',
    }
    conn.execute.return_value.fetchall.return_value = []

    ready, reason = deployment_run_auto_completion._readiness(conn, "run-settling")

    assert reason == ""
    assert ready is not None
    assert ready["remaining"] == []

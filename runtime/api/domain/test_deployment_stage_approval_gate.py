"""Deployment stage approval reuses the lifecycle approval verdict."""

from __future__ import annotations

import pytest

from runtime.api.deployment_stage_approval_fixture import OpenConnection
from yoke_core.domain import deployment_run_approval
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.deployment_approval_requests import (
    deployment_stage_is_approved,
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_run_approval import emit_run_approval


def _prod_environment_id(conn) -> int:
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Gate test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Gate test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
        ).fetchone()[0]
    )


def _seed_run(conn, *, flow_id, run_id, stages_json, created_by="1"):
    environment_id = _prod_environment_id(conn)
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES (%s, 1, %s, %s, '2026-07-26T00:00:00Z')",
        (flow_id, flow_id, stages_json),
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, current_stage, created_by, created_at) "
        "VALUES (%s, 1, %s, 'persistent', %s, 'executing', "
        "'approve-prod', %s, '2026-07-26T00:00:00Z')",
        (run_id, flow_id, environment_id, created_by),
    )
    conn.commit()


def test_missing_stage_approvers_fail_closed(test_db):
    create_decision_request_tables(test_db)
    _seed_run(
        test_db,
        flow_id="gate-missing",
        run_id="run-gate-missing",
        stages_json=('[{"name":"approve-prod","step_runner":"human-approval"}]'),
    )
    with pytest.raises(ValueError, match="has no approvers"):
        evaluate_deployment_stage_approval(
            test_db,
            run_id="run-gate-missing",
        )


def test_reject_does_not_satisfy_and_does_not_open_a_new_request(test_db):
    create_decision_request_tables(test_db)
    owner = test_db.execute(
        "SELECT id FROM actors ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    role = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9401, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') "
        "ON CONFLICT DO NOTHING",
        (owner, role),
    )
    _seed_run(
        test_db,
        flow_id="gate-reject",
        run_id="run-gate-reject",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )
    pending = evaluate_deployment_stage_approval(
        test_db,
        run_id="run-gate-reject",
    )
    resolve_decision_request(
        test_db,
        pending.request_id,
        actor_id=owner,
        action="reject",
    )
    rejected = evaluate_deployment_stage_approval(
        test_db,
        run_id="run-gate-reject",
    )
    assert rejected.satisfied is False
    assert rejected.resolution_action == "reject"
    assert rejected.request_id == pending.request_id


def test_named_actor_is_the_configured_authority(test_db):
    create_decision_request_tables(test_db)
    actor = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    _seed_run(
        test_db,
        flow_id="gate-named",
        run_id="run-gate-named",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            f'"approvals":{{"roles":[],"actors":[{actor}]}}}}]'
        ),
    )
    verdict = evaluate_deployment_stage_approval(
        test_db,
        run_id="run-gate-named",
        originator_actor_id=actor,
    )
    named = [
        int(row[0])
        for row in test_db.execute(
            "SELECT actor_id FROM decision_request_actor_authorities "
            "WHERE request_id=%s",
            (verdict.request_id,),
        ).fetchall()
    ]
    assert named == [actor]
    roles = test_db.execute(
        "SELECT role_name FROM decision_request_role_authorities WHERE request_id=%s",
        (verdict.request_id,),
    ).fetchall()
    assert roles == []


def test_all_mode_stage_stays_unapproved_until_every_box_decides(
    test_db,
    monkeypatch,
):
    create_decision_request_tables(test_db)
    named = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    owner = int(
        test_db.execute("SELECT id FROM actors ORDER BY id DESC LIMIT 1").fetchone()[0]
    )
    assert owner != named
    role = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9402, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') ON CONFLICT DO NOTHING",
        (owner, role),
    )
    _seed_run(
        test_db,
        flow_id="gate-every-approver",
        run_id="run-gate-every-approver",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            f'"approvals":{{"roles":["owner"],"actors":[{named}],'
            '"mode":"all"}},'
            '{"name":"release","step_runner":"auto"}]'
        ),
    )
    open_conn = OpenConnection(test_db)
    monkeypatch.setattr(deployment_run_approval, "connect", lambda: open_conn)

    partial = deployment_run_approval.approve_run(
        "run-gate-every-approver",
        actor_id=owner,
        session_id="stage-session",
        note="owner cleared prod",
    )
    assert partial.stage_approved is False
    assert partial.approval_progress["satisfied"] == 1
    assert partial.approval_progress["required"] == 2
    assert (
        emit_run_approval(
            partial, actor_id=str(owner), session_id="stage-session", note=None
        )
        is None
    )
    assert (
        deployment_stage_is_approved(
            test_db,
            run_id="run-gate-every-approver",
            stage_id="approve-prod",
        )
        is False
    )

    finished = deployment_run_approval.approve_run(
        "run-gate-every-approver",
        actor_id=named,
        session_id="stage-session",
        note="named approver cleared prod",
    )
    assert finished.stage_approved is True
    assert finished.next_stage == "release"
    assert (
        deployment_stage_is_approved(
            test_db,
            run_id="run-gate-every-approver",
            stage_id="approve-prod",
        )
        is True
    )

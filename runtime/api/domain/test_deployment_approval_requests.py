"""Deployment approval requests preserve run state until the runner consumes them."""

from __future__ import annotations

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain import deployment_run_approval
from yoke_core.domain.deployment_approval_requests import (
    emit_deployment_completion,
    deployment_stage_decision,
    deployment_stage_is_approved,
    dispatch_deployment_stage_approval,
    ensure_deployment_stage_approval,
)


class _OpenConnection:
    """Keep the fixture-owned connection open across runtime helper calls."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        return None


def test_deployment_stage_request_is_idempotent_and_runner_consumable(
    test_db, monkeypatch,
):
    create_decision_request_tables(test_db)
    originator = test_db.execute(
        "SELECT id FROM actors ORDER BY id LIMIT 1"
    ).fetchone()[0]
    owner = test_db.execute(
        "SELECT id FROM actors ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    role = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9301, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
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
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES ('approval-proof', 1, 'Approval proof', "
        "'[{\"name\":\"production\",\"step_runner\":\"human-approval\"},"
        "{\"name\":\"release\",\"step_runner\":\"auto\"}]', "
        "'2026-07-26T00:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, current_stage, created_at) "
        "VALUES ('run-approval-proof', 1, 'approval-proof', 'persistent', "
        "'production', 'executing', 'production', '2026-07-26T00:00:00Z')"
    )
    test_db.commit()

    request, created = ensure_deployment_stage_approval(
        test_db, run_id="run-approval-proof",
        originator_actor_id=originator,
    )
    repeated, created_again = ensure_deployment_stage_approval(
        test_db, run_id="run-approval-proof",
        originator_actor_id=originator,
    )
    assert created is True
    assert created_again is False
    assert repeated["id"] == request["id"]
    assert deployment_stage_is_approved(
        test_db, run_id="run-approval-proof", stage_id="production",
    ) is False
    assert deployment_stage_decision(
        test_db, run_id="run-approval-proof", stage_id="production",
    ) is None
    assert test_db.execute(
        "SELECT current_stage FROM deployment_runs "
        "WHERE id='run-approval-proof'"
    ).fetchone()[0] == "production"

    open_conn = _OpenConnection(test_db)
    import yoke_core.domain.db_helpers as db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: open_conn)
    assert dispatch_deployment_stage_approval(
        "run-approval-proof", "production",
    ) == (-2, "")

    monkeypatch.setattr(
        deployment_run_approval, "connect", lambda: open_conn,
    )
    approval = deployment_run_approval.approve_run(
        "run-approval-proof",
        actor_id=owner,
        session_id="approval-session",
        note="production checks passed",
    )
    assert approval.decision_request_id == request["id"]
    assert approval.next_stage == "release"
    assert deployment_stage_is_approved(
        test_db, run_id="run-approval-proof", stage_id="production",
    ) is True
    assert deployment_stage_decision(
        test_db, run_id="run-approval-proof", stage_id="production",
    ) == "approve"
    assert dispatch_deployment_stage_approval(
        "run-approval-proof", "production",
    ) == (0, "")
    assert test_db.execute(
        "SELECT current_stage FROM deployment_runs "
        "WHERE id='run-approval-proof'"
    ).fetchone()[0] == "production"

    test_db.execute(
        "UPDATE deployment_runs SET created_by=%s "
        "WHERE id='run-approval-proof'",
        (str(originator),),
    )
    event_id, inserted = emit_deployment_completion(
        test_db,
        run_id="run-approval-proof",
        event_name="DeploymentRunSucceeded",
        outcome="completed",
        reason="Deployment run completed",
        context={"flow": "approval-proof"},
    )
    assert inserted == len({int(originator), int(owner)})
    recipients = test_db.execute(
        "SELECT actor_id FROM addressed_event_deliveries "
        "WHERE event_id=%s ORDER BY actor_id",
        (event_id,),
    ).fetchall()
    assert [int(row[0]) for row in recipients] == sorted(
        {int(originator), int(owner)}
    )


def test_deployment_completion_event_and_deliveries_share_transaction(
    test_db,
):
    create_decision_request_tables(test_db)
    initiator = int(test_db.execute(
        "SELECT id FROM actors ORDER BY id LIMIT 1"
    ).fetchone()[0])
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES ('completion-proof', 1, 'Completion proof', '[]', "
        "'2026-07-26T00:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, created_by, created_at) "
        "VALUES ('run-completion-proof', 1, 'completion-proof', 'persistent', "
        "'production', 'succeeded', %s, '2026-07-26T00:00:00Z')",
        (str(initiator),),
    )
    test_db.commit()

    event_id, inserted = emit_deployment_completion(
        test_db,
        run_id="run-completion-proof",
        event_name="DeploymentRunSucceeded",
        outcome="completed",
        reason="Deployment run completed",
        context={"flow": "completion-proof"},
    )
    assert inserted == 1
    assert test_db.execute(
        "SELECT COUNT(*) FROM addressed_event_deliveries WHERE event_id=%s",
        (event_id,),
    ).fetchone()[0] == 1
    test_db.rollback()
    assert test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_id=%s", (event_id,),
    ).fetchone()[0] == 0
    assert test_db.execute(
        "SELECT COUNT(*) FROM addressed_event_deliveries WHERE event_id=%s",
        (event_id,),
    ).fetchone()[0] == 0

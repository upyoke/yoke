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


def _prod_environment_id(conn) -> int:
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Approval test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Approval test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
        ).fetchone()[0]
    )


def test_deployment_stage_request_is_idempotent_and_runner_consumable(
    test_db, monkeypatch,
):
    create_decision_request_tables(test_db)
    environment_id = _prod_environment_id(test_db)
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
        "'[{\"name\":\"approve-prod\",\"step_runner\":\"human-approval\"},"
        "{\"name\":\"release\",\"step_runner\":\"auto\"}]', "
        "'2026-07-26T00:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, current_stage, created_at) "
        "VALUES ('run-approval-proof', 1, 'approval-proof', 'persistent', "
        "%s, 'executing', 'approve-prod', '2026-07-26T00:00:00Z')",
        (environment_id,),
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
        test_db, run_id="run-approval-proof", stage_id="approve-prod",
    ) is False
    assert deployment_stage_decision(
        test_db, run_id="run-approval-proof", stage_id="approve-prod",
    ) is None
    assert test_db.execute(
        "SELECT current_stage FROM deployment_runs "
        "WHERE id='run-approval-proof'"
    ).fetchone()[0] == "approve-prod"

    open_conn = _OpenConnection(test_db)
    import yoke_core.domain.db_helpers as db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: open_conn)
    assert dispatch_deployment_stage_approval(
        "run-approval-proof", "approve-prod",
    ) == (-2, "")

    monkeypatch.setattr(
        deployment_run_approval, "connect", lambda: open_conn,
    )
    approval = deployment_run_approval.approve_run(
        "run-approval-proof",
        actor_id=owner,
        session_id="approval-session",
        note="prod checks passed",
    )
    assert approval.decision_request_id == request["id"]
    assert approval.next_stage == "release"
    assert deployment_stage_is_approved(
        test_db, run_id="run-approval-proof", stage_id="approve-prod",
    ) is True
    assert deployment_stage_decision(
        test_db, run_id="run-approval-proof", stage_id="approve-prod",
    ) == "approve"
    assert dispatch_deployment_stage_approval(
        "run-approval-proof", "approve-prod",
    ) == (0, "")
    assert test_db.execute(
        "SELECT current_stage FROM deployment_runs "
        "WHERE id='run-approval-proof'"
    ).fetchone()[0] == "approve-prod"



def test_deployment_completion_event_shares_the_caller_transaction(
    test_db,
):
    create_decision_request_tables(test_db)
    environment_id = _prod_environment_id(test_db)
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
        "%s, 'succeeded', %s, '2026-07-26T00:00:00Z')",
        (environment_id, str(initiator)),
    )
    test_db.commit()

    event_id = emit_deployment_completion(
        test_db,
        run_id="run-completion-proof",
        event_name="DeploymentRunSucceeded",
        outcome="completed",
        context={"flow": "completion-proof"},
    )
    assert test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_id=%s", (event_id,),
    ).fetchone()[0] == 1
    test_db.rollback()
    assert test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_id=%s", (event_id,),
    ).fetchone()[0] == 0

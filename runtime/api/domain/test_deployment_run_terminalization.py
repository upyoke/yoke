"""Deployment-run terminalization is guarded and transactionally audited."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import deployment_run_terminalization as terminalization


class _OpenConnection:
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        return None


def _seed_run(test_db, run_id: str, status: str) -> None:
    flow_id = f"flow-{run_id}"
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES (%s, 1, %s, '[]', '2026-08-05T00:00:00Z')",
        (flow_id, flow_id),
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_env, status, current_stage, created_at) "
        "VALUES (%s, 1, %s, 'production', %s, 'hosted-release', "
        "'2026-08-05T00:00:00Z')",
        (run_id, flow_id, status),
    )
    test_db.commit()


def _bind_connection(monkeypatch, test_db) -> None:
    monkeypatch.setattr(
        terminalization, "connect", lambda: _OpenConnection(test_db),
    )


def test_terminalization_updates_run_and_appends_permanent_audit(
    test_db, monkeypatch,
):
    _seed_run(test_db, "run-terminalize-proof", "executing")
    _bind_connection(monkeypatch, test_db)

    result = terminalization.terminalize_run(
        "run-terminalize-proof",
        disposition="cancelled",
        reason="External workflow no longer exists",
        actor_id=None,
        session_id="terminalization-session",
    )

    assert result.prior_status == "executing"
    assert result.final_status == "cancelled"
    run = test_db.execute(
        "SELECT status, completed_at FROM deployment_runs WHERE id=%s",
        (result.run_id,),
    ).fetchone()
    assert run[0] == "cancelled"
    assert run[1] == result.terminalized_at
    event = test_db.execute(
        "SELECT source_type, severity, actor_id, envelope FROM events "
        "WHERE event_id=%s",
        (result.event_id,),
    ).fetchone()
    assert event[0] == "backend"
    assert event[1] == "STATUS"
    assert event[2] is None
    envelope = event[3] if isinstance(event[3], dict) else json.loads(event[3])
    assert envelope["event_name"] == "DeploymentRunTerminalized"
    assert envelope["context"] == {
        "run_id": "run-terminalize-proof",
        "prior_status": "executing",
        "final_status": "cancelled",
        "current_stage": "hosted-release",
        "reason": "External workflow no longer exists",
        "terminalized_at": result.terminalized_at,
        "terminalized_by_actor_id": None,
        "terminalized_by_session_id": "terminalization-session",
    }


def test_terminalization_refuses_an_already_terminal_run(test_db, monkeypatch):
    _seed_run(test_db, "run-already-failed", "failed")
    _bind_connection(monkeypatch, test_db)

    with pytest.raises(
        terminalization.RunTerminalizationRejected,
        match="terminal status 'failed'",
    ):
        terminalization.terminalize_run(
            "run-already-failed",
            disposition="cancelled",
            reason="Should not overwrite history",
            actor_id=1,
            session_id="terminalization-session",
        )
    assert test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_name=%s",
        (terminalization.TERMINALIZATION_EVENT,),
    ).fetchone()[0] == 0


def test_audit_failure_rolls_back_the_run_state(test_db, monkeypatch):
    _seed_run(test_db, "run-audit-rollback", "created")
    _bind_connection(monkeypatch, test_db)
    monkeypatch.setattr(
        terminalization,
        "_append_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no event")),
    )

    with pytest.raises(RuntimeError, match="no event"):
        terminalization.terminalize_run(
            "run-audit-rollback",
            disposition="failed",
            reason="Creation never advanced",
            actor_id=1,
            session_id="terminalization-session",
        )
    assert test_db.execute(
        "SELECT status, completed_at FROM deployment_runs WHERE id=%s",
        ("run-audit-rollback",),
    ).fetchone() == ("created", None)

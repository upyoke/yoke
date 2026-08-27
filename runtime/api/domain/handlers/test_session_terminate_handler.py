"""Public terminate surface persists a kill the roster classifies as ended."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.test_sessions import _register
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STATES
from yoke_core.domain.handlers.session_termination import handle_session_terminate
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_list_read import list_sessions


pytest_plugins = ("runtime.api.test_sessions",)

NOW = "2026-08-27T12:00:00Z"
MACHINE_ID = "11111111-1111-4111-8111-111111111111"


class _HandlerConnection:
    """Expose the test connection to the handler without closing the fixture."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.committed = False

    def commit(self) -> None:
        self._conn.commit()
        self.committed = True

    def close(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


@pytest.fixture(autouse=True)
def _termination_schema_and_events(conn, monkeypatch):
    create_session_control_tables(conn)
    conn.execute(
        "INSERT INTO actors (id,kind,created_at) VALUES "
        "(41,'human',%s),(42,'human',%s) ON CONFLICT (id) DO NOTHING",
        (NOW, NOW),
    )
    conn.commit()
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end.emit_release_claims_branch_event",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
        lambda *_args, **_kwargs: None,
    )


def _request() -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": "session_control.session.terminate",
            "actor": {"actor_id": "41", "session_id": "operator"},
            "target": {"kind": "global"},
            "payload": {
                "session_id": "worker",
                "reason": "worker unresponsive cleanup",
            },
        }
    )


def test_public_terminate_commits_ended_killed_and_releases_claims(
    conn, monkeypatch
) -> None:
    _register(conn, session_id="operator", actor_id=41, mode="operator")
    _register(
        conn,
        session_id="worker",
        actor_id=42,
        machine_id=MACHINE_ID,
        native_thread_id="native-worker-1",
    )
    insert_item(conn, id=910, workflow_id="issue")
    claim_work(conn, session_id="worker", item_id=910)
    conn.commit()

    handler_conn = _HandlerConnection(conn)
    monkeypatch.setattr(
        "yoke_core.domain.handlers.session_termination.open_connection",
        lambda: handler_conn,
    )

    outcome = handle_session_terminate(_request())

    assert outcome.primary_success
    assert outcome.error is None
    assert handler_conn.committed is True
    assert outcome.result_payload["session"]["terminated_at"]
    assert outcome.result_payload["deduplicated"] is False

    conn.rollback()
    row = dict(
        conn.execute(
            "SELECT ended_at,terminated_at,termination_reason FROM harness_sessions "
            "WHERE session_id='worker'"
        ).fetchone()
    )
    assert row["ended_at"] and row["terminated_at"]
    assert row["termination_reason"] == "worker unresponsive cleanup"
    claim = conn.execute(
        "SELECT released_at,release_reason FROM work_claims WHERE session_id='worker'"
    ).fetchone()
    assert claim["released_at"] and claim["release_reason"] == "session_ended"

    liveness = session_liveness(row, now=datetime(2026, 8, 27, tzinfo=timezone.utc))
    assert liveness == LIVENESS_ENDED
    assert "terminated" not in LIVENESS_STATES
    with pytest.raises(ValueError, match="terminated"):
        list_sessions(liveness="terminated")

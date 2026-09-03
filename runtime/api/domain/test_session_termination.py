"""Domain coverage for permanent, atomic session termination."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.test_sessions import _register
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STATES
from yoke_core.domain.handlers.session_termination import handle_session_terminate
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_message_routing import session_liveness
from yoke_core.domain.session_termination import terminate_session
from yoke_core.domain.sessions import SessionError, claim_work
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.work_claim_targets import make_steering_target


pytest_plugins = ("runtime.api.test_sessions",)

NOW = "2026-08-26T12:00:00Z"
MACHINE_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _termination_schema_and_events(conn, monkeypatch):
    create_session_control_tables(conn)
    conn.execute(
        "INSERT INTO actors (id,kind,created_at) VALUES "
        "(41,'human',%s),(42,'human',%s),(43,'human',%s)",
        (NOW, NOW, NOW),
    )
    conn.commit()
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_termination.emit_session_terminated",
        lambda session_id, context: events.append((session_id, context)),
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end.emit_release_claims_branch_event",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.sessions_render_end._sa._emit_session_event",
        lambda *args, **kwargs: None,
    )
    return events


def _register_operator_and_target(conn, *, target="worker") -> None:
    _register(
        conn,
        session_id="operator",
        actor_id=41,
        mode="operator",
    )
    _register(
        conn,
        session_id=target,
        actor_id=42,
        machine_id=MACHINE_ID,
        native_thread_id="native-worker-1",
    )


def _add_target_claim(conn, *, session_id="worker", item_id=900) -> None:
    insert_item(conn, id=item_id, workflow_id="issue")
    claim_work(conn, session_id=session_id, item_id=item_id)


def _add_open_message(conn, *, session_id="worker", state="injected") -> None:
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id,sender_actor_id,sender_session_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES "
        "('message-1',41,'operator','finish','sha256:body','{}',%s,"
        "'2026-08-27T12:00:00Z')",
        (NOW,),
    )
    conn.execute(
        "INSERT INTO session_message_recipients "
        "(message_id,session_id,project_id,resolution_evidence,routing_snapshot,"
        "state,created_at,wake_after,injection_lease_id,injection_leased_at,"
        "injection_lease_expires_at) VALUES "
        "('message-1',%s,1,'{}','{}',%s,%s,%s,'lease-1',%s,"
        "'2026-08-27T12:00:00Z')",
        (session_id, state, NOW, NOW, NOW),
    )
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,started_at) "
        "VALUES ('attempt-1','message-1',%s,'hook','lease-1',%s)",
        (session_id, NOW),
    )
    conn.commit()


def _terminate(conn, **overrides):
    arguments = {
        "target_session_id": "worker",
        "actor_id": 41,
        "caller_session_id": "operator",
        "reason": "worker completed",
    }
    arguments.update(overrides)
    return terminate_session(conn, **arguments)


class _HandlerConnection:
    """Expose the fixture connection to the handler without closing it."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.committed = False

    def commit(self) -> None:
        self._conn.commit()
        self.committed = True

    def close(self) -> None:
        return None

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_operator_termination_ends_silences_releases_and_queues_reap(
    conn, _termination_schema_and_events
) -> None:
    _register_operator_and_target(conn)
    _add_target_claim(conn)
    _add_open_message(conn)

    result = _terminate(conn)

    row = conn.execute(
        "SELECT ended_at,terminated_at,terminated_by_actor_id,"
        "terminated_by_session_id,termination_reason FROM harness_sessions "
        "WHERE session_id='worker'"
    ).fetchone()
    assert row["ended_at"] and row["terminated_at"]
    assert row["terminated_by_actor_id"] == 41
    assert row["terminated_by_session_id"] == "operator"
    assert row["termination_reason"] == "worker completed"
    claim = conn.execute(
        "SELECT released_at,release_reason FROM work_claims WHERE session_id='worker'"
    ).fetchone()
    assert claim["released_at"] and claim["release_reason"] == "session_ended"
    recipient = conn.execute(
        "SELECT state,cancelled_at,injection_lease_id FROM session_message_recipients"
    ).fetchone()
    assert tuple(recipient) == ("cancelled", recipient["cancelled_at"], None)
    assert recipient["cancelled_at"]
    attempt = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts"
    ).fetchone()
    assert attempt["completed_at"] and attempt["result_code"] == "session_terminated"
    reap = conn.execute(
        "SELECT state,machine_id,target_native_thread_id "
        "FROM session_termination_reaps WHERE target_session_id='worker'"
    ).fetchone()
    assert tuple(reap) == ("pending", MACHINE_ID, "native-worker-1")
    assert result["cancelled_recipient_count"] == 1
    assert result["reap_state"] == "pending"
    assert result["deduplicated"] is False
    assert _termination_schema_and_events == [
        (
            "worker",
            {
                "terminated_by_actor_id": 41,
                "terminated_by_session_id": "operator",
                "authority": "operator",
                "reason": "worker completed",
                "cancelled_recipient_count": 1,
                "reap_state": "pending",
                "was_ended": False,
                "chain_override_authorized": False,
            },
        )
    ]


def test_termination_is_idempotent_without_requeueing_or_reemitting(
    conn, _termination_schema_and_events
) -> None:
    _register_operator_and_target(conn)
    first = _terminate(conn)
    second = _terminate(conn, reason="duplicate request")

    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    assert second["cancelled_recipient_count"] == 0
    assert len(_termination_schema_and_events) == 1
    row = conn.execute(
        "SELECT termination_reason FROM harness_sessions WHERE session_id='worker'"
    ).fetchone()
    assert row[0] == "worker completed"


def test_termination_requires_a_nonblank_reason(conn) -> None:
    _register_operator_and_target(conn)

    with pytest.raises(SessionError) as exc_info:
        _terminate(conn, reason="   ")

    assert exc_info.value.code == "TERMINATION_REASON_REQUIRED"
    assert (
        conn.execute(
            "SELECT terminated_at FROM harness_sessions WHERE session_id='worker'"
        ).fetchone()[0]
        is None
    )


def test_steering_claim_authorizes_termination_and_unrelated_session_does_not(
    conn,
) -> None:
    _register(conn, session_id="steering", actor_id=43, mode="do")
    _register(conn, session_id="unrelated", actor_id=41, mode="wait")
    _register(conn, session_id="worker", actor_id=42)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES ('steering','steering',%s,'exclusive',%s,%s)",
        (make_steering_target(1).scope_json(), NOW, NOW),
    )
    conn.commit()

    with pytest.raises(SessionError, match="operator mode or a live steering seat"):
        terminate_session(
            conn,
            target_session_id="worker",
            actor_id=41,
            caller_session_id="unrelated",
            reason="not authorized",
        )

    result = terminate_session(
        conn,
        target_session_id="worker",
        actor_id=43,
        caller_session_id="steering",
        reason="steering completed worker",
    )
    assert result["session"]["terminated_at"]


def test_chain_pending_failure_rolls_back_and_explicit_override_converges(conn) -> None:
    _register_operator_and_target(conn)
    _add_target_claim(conn)
    _add_open_message(conn)
    envelope = {
        "max_chain_steps": 3,
        "chain_checkpoint": {
            "step": 1,
            "action": "dash",
            "chainable": True,
            "handler_outcome": "completed",
        },
    }
    conn.execute(
        "UPDATE harness_sessions SET offer_envelope=%s WHERE session_id='worker'",
        (json.dumps(envelope),),
    )
    conn.commit()

    with pytest.raises(SessionError) as exc_info:
        _terminate(conn)
    assert exc_info.value.code == "CHAIN_PENDING"
    conn.rollback()  # registered handler performs this rollback on every failure
    target = conn.execute(
        "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id='worker'"
    ).fetchone()
    assert tuple(target) == (None, None)
    assert (
        conn.execute("SELECT state FROM session_message_recipients").fetchone()[0]
        == "injected"
    )
    assert (
        conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id='worker'"
        ).fetchone()[0]
        is None
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM session_termination_reaps").fetchone()[0]
        == 0
    )

    result = _terminate(
        conn,
        override_chain_end=True,
        chain_end_rationale="operator intentionally abandons the pending chain",
    )
    assert result["session"]["terminated_at"]


def test_public_terminate_commits_ended_killed_and_releases_claims(
    conn, monkeypatch
) -> None:
    # Not under handlers/: pytest_plugins there shadows path-claim ``conn``.
    _register_operator_and_target(conn)
    _add_target_claim(conn, item_id=910)
    handler_conn = _HandlerConnection(conn)
    monkeypatch.setattr(
        "yoke_core.domain.handlers.session_termination.open_connection",
        lambda: handler_conn,
    )
    outcome = handle_session_terminate(
        FunctionCallRequest.model_validate(
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
    )

    assert outcome.primary_success
    assert outcome.error is None
    assert handler_conn.committed is True
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
    assert (
        session_liveness(row, now=datetime(2026, 8, 27, tzinfo=timezone.utc))
        == LIVENESS_ENDED
    )
    assert "terminated" not in LIVENESS_STATES
    with pytest.raises(ValueError, match="terminated"):
        list_sessions(liveness="terminated")

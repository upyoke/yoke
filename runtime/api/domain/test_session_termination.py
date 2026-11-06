"""Domain coverage for permanent, atomic session termination."""

from __future__ import annotations

from runtime.api.sessions_test_support import conn as conn  # noqa: F401

from runtime.api.domain.session_termination_test_support import (
    MACHINE_ID as MACHINE_ID,
    NOW as NOW,
    _HandlerConnection as _HandlerConnection,
    _add_open_message as _add_open_message,
    _add_target_claim as _add_target_claim,
    _register_operator_and_target as _register_operator_and_target,
    _terminate as _terminate,
    _termination_schema_and_events as _termination_schema_and_events,
)


import json
from datetime import datetime, timezone

import pytest

from runtime.api.sessions_test_support import _register
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_control.liveness import LIVENESS_ENDED, LIVENESS_STATES
from yoke_core.domain.handlers.session_termination import handle_session_terminate
from yoke_core.domain.session_staleness import session_liveness
from yoke_core.domain.session_termination import (
    terminate_cancelled_launch_session,
    terminate_session,
)
from yoke_core.domain.sessions import SessionError
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.work_claim_targets import make_steering_target


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
                "authority": "steering",
                "reason": "worker completed",
                "cancelled_recipient_count": 1,
                "reap_state": "pending",
                "was_ended": False,
                "allow_resume_in_flight": False,
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
        "UPDATE harness_sessions SET launch_origin='yoke' WHERE session_id='worker'"
    )
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES ('steering','steering',%s,'exclusive',%s,%s)",
        (make_steering_target(1).scope_json(), NOW, NOW),
    )
    conn.commit()

    with pytest.raises(SessionError, match="live steering seat"):
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


def test_launch_cancel_ends_its_session_without_a_steering_seat(
    conn, _termination_schema_and_events
) -> None:
    _register(conn, session_id="requester", actor_id=41, mode="wait")
    _register(conn, session_id="worker", actor_id=42, machine_id=MACHINE_ID)
    conn.execute(
        "UPDATE harness_sessions SET launch_origin='yoke' WHERE session_id='worker'"
    )

    result = terminate_cancelled_launch_session(
        conn,
        target_session_id="worker",
        actor_id=41,
        caller_session_id="requester",
        reason="launch cancelled before its instructions were delivered",
    )

    assert result["session"]["terminated_at"]
    assert result["reap_state"] == "pending"
    assert _termination_schema_and_events[0][1]["authority"] == "launch_cancel"


def test_termination_ignores_checkpoint_budget(conn) -> None:
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

    result = _terminate(conn)
    assert result["session"]["terminated_at"]


def test_public_terminate_commits_ended_killed_and_releases_claims(
    conn, monkeypatch
) -> None:
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

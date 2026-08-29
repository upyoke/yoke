"""One-shot explicit session wake behavior over the existing relay path."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain.handlers import session_wake as session_wake_handler
from yoke_core.domain import session_manual_wake
from yoke_core.domain.session_manual_wake import (
    request_session_wake,
    wait_for_session_wake_result,
)
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    message_connection,
)


def test_manual_wake_forces_the_stopped_route_for_an_active_session() -> None:
    conn = message_connection()

    result = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=None,
        now=NOW,
    )

    assert result["target_session_id"] == "s2"
    assert result["target_liveness"] == "active"
    assert result["result_code"] == "queued"
    assert result["recovery"] == f"yoke messages get {result['message_id']}"
    details = message_details(conn, result["message_id"])
    assert details["body"] == native_wake_instruction(result["message_id"])
    recipient = details["recipients"][0]
    assert recipient["routing_snapshot"][EXPLICIT_WAKE_ROUTING_FLAG] is True
    routing = recipient["routing_snapshot"]["messageability"]
    assert routing["wake_operation"] == "message_stopped"

    candidates = wake_eligible_recipients(conn, now=NOW)
    assert len(candidates) == 1
    assert candidates[0]["session_id"] == "s2"
    assert candidates[0]["liveness"] == "active"
    assert candidates[0]["wake_mode"] == WakeMode.WAITING.value


def test_manual_wake_is_one_native_attempt_even_when_the_attempt_fails() -> None:
    conn = message_connection()
    result = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id="s2",
        public_ref=None,
        prompt="Continue the existing task.",
        now=NOW,
    )
    candidate = wake_eligible_recipients(conn, now=NOW)[0]
    claim = claim_wake_attempt(
        conn,
        candidate=candidate,
        now="2026-08-22T16:00:01Z",
    )
    assert claim is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code='failed' "
        "WHERE attempt_id=?",
        ("2026-08-22T16:00:02Z", claim.attempt_id),
    )
    conn.commit()

    assert message_details(conn, result["message_id"])["body"] == (
        "Continue the existing task."
    )
    settled = wait_for_session_wake_result(conn, result, wait_seconds=0)
    assert settled["attempt"]["attempt_id"] == claim.attempt_id
    assert settled["result_code"] == "failed"
    assert settled["recovery"] is None
    assert wake_eligible_recipients(conn, now=NOW + timedelta(hours=1)) == []


def test_item_target_resolves_its_current_work_claim_holder() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE work_claims SET session_id=? WHERE id=1",
        (NATIVE_WAKE_SESSION_ID,),
    )
    conn.commit()

    result = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id=None,
        public_ref="ALP-1",
        prompt="Check the current work.",
        now=NOW,
    )

    assert result["target_session_id"] == NATIVE_WAKE_SESSION_ID
    details = message_details(conn, result["message_id"])
    assert details["selector_snapshot"]["public_refs"] == ["ALP-1"]


def test_programmatic_wake_requires_project_write_authority() -> None:
    conn = message_connection()

    with pytest.raises(SessionMessageError) as refused:
        request_session_wake(
            conn,
            actor_id=11,
            caller_session_id=None,
            session_id="s2",
            public_ref=None,
            prompt=None,
            now=NOW,
        )

    assert refused.value.code == "unauthorized_target"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


def test_registered_wake_handler_accepts_a_verified_actor_without_session(
    monkeypatch,
) -> None:
    conn = message_connection()
    monkeypatch.setattr(session_wake_handler, "open_connection", lambda: conn)
    monkeypatch.setattr(
        session_manual_wake,
        "wait_for_session_wake_result",
        lambda _conn, result: result,
    )
    request = FunctionCallRequest(
        function="session_control.session.wake",
        actor=ActorContext(actor_id="10", session_id=""),
        target=TargetRef(kind="global"),
        payload={"session_id": "s2", "idempotency_key": "watchdog:s2"},
    )

    outcome = session_wake_handler.handle_session_wake(request)

    assert outcome.primary_success is True
    assert outcome.result_payload["target_session_id"] == "s2"
    assert outcome.result_payload["deduplicated"] is False


def test_terminated_session_stays_non_wakeable_when_displayed_as_ended() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET ended_at=?,terminated_at=? WHERE session_id='s2'",
        ("2026-08-22T15:59:00Z", "2026-08-22T15:59:00Z"),
    )
    conn.commit()

    with pytest.raises(SessionMessageError) as refused:
        request_session_wake(
            conn,
            actor_id=10,
            caller_session_id="s1",
            session_id="s2",
            public_ref=None,
            prompt=None,
            now=NOW,
        )

    assert refused.value.code == "session_terminated"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


def test_idempotency_key_returns_the_same_explicit_wake_receipt() -> None:
    conn = message_connection()
    request = dict(
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=None,
        idempotency_key="resume-s2-after-watchdog",
        now=NOW,
    )

    first = request_session_wake(conn, **request)
    repeated = request_session_wake(conn, **request)
    candidate = wake_eligible_recipients(conn, now=NOW)[0]
    assert claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:00:01Z")
    conn.commit()
    repeated_in_grace = request_session_wake(
        conn, **{**request, "now": NOW + timedelta(seconds=2)}
    )

    assert first["message_id"] == repeated["message_id"]
    assert first["message_id"] == repeated_in_grace["message_id"]
    assert first["deduplicated"] is False
    assert repeated["deduplicated"] is True
    assert repeated_in_grace["deduplicated"] is True
    assert repeated_in_grace["wake_attempt_count"] == 1
    assert repeated_in_grace["last_wake_at"] == "2026-08-22T16:00:01Z"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 1
    )


def test_second_explicit_wake_is_refused_inside_recipient_grace_window() -> None:
    conn = message_connection()
    first = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=None,
        idempotency_key="first-wake",
        now=NOW,
    )
    candidate = wake_eligible_recipients(conn, now=NOW)[0]
    assert claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:00:01Z")
    conn.commit()

    with pytest.raises(SessionMessageError) as refused:
        request_session_wake(
            conn,
            actor_id=10,
            caller_session_id=None,
            session_id="s2",
            public_ref=None,
            prompt=None,
            idempotency_key="second-wake",
            now=NOW + timedelta(seconds=2),
        )

    assert refused.value.code == "wake_in_flight"
    assert first["message_id"] in str(refused.value)
    assert "wake_attempt_count=1" in str(refused.value)
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1

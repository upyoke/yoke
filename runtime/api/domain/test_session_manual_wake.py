"""One-shot manual session wake behavior over the existing relay path."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_contracts.session_control.wake import MANUAL_WAKE_SELECTOR_FLAG
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_core.domain.session_manual_wake import (
    request_manual_wake,
    wait_for_manual_wake_result,
)
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.sessions_analytics import SessionError
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
)


def _operator_connection():
    conn = message_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='operator' WHERE session_id='s1'"
    )
    conn.commit()
    return conn


def test_manual_wake_forces_the_stopped_route_for_an_active_session() -> None:
    conn = _operator_connection()

    result = request_manual_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id="s2",
        item_ref=None,
        prompt=None,
        now=NOW,
    )

    assert result["target_session_id"] == "s2"
    assert result["target_liveness"] == "active"
    assert result["result_code"] == "queued"
    assert result["recovery"] == f"yoke messages get {result['message_id']}"
    details = message_details(conn, result["message_id"])
    assert details["body"] == native_wake_instruction(result["message_id"])
    assert details["selector_snapshot"][MANUAL_WAKE_SELECTOR_FLAG] is True
    routing = details["recipients"][0]["routing_snapshot"]["messageability"]
    assert routing["wake_operation"] == "message_stopped"

    candidates = wake_eligible_recipients(conn, now=NOW)
    assert len(candidates) == 1
    assert candidates[0]["session_id"] == "s2"
    assert candidates[0]["liveness"] == "active"
    assert candidates[0]["wake_mode"] == WakeMode.WAITING.value


def test_manual_wake_is_one_native_attempt_even_when_the_attempt_fails() -> None:
    conn = _operator_connection()
    result = request_manual_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id="s2",
        item_ref=None,
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
    settled = wait_for_manual_wake_result(conn, result, wait_seconds=0)
    assert settled["attempt"]["attempt_id"] == claim.attempt_id
    assert settled["result_code"] == "failed"
    assert settled["recovery"] is None
    assert wake_eligible_recipients(conn, now=NOW + timedelta(hours=1)) == []


def test_item_target_resolves_its_current_work_claim_holder() -> None:
    conn = _operator_connection()

    result = request_manual_wake(
        conn,
        actor_id=10,
        caller_session_id="s1",
        session_id=None,
        item_ref="ALP-1",
        prompt="Check the current work.",
        now=NOW,
    )

    assert result["target_session_id"] == "s1"
    details = message_details(conn, result["message_id"])
    assert details["selector_snapshot"]["item_refs"] == ["ALP-1"]


def test_manual_wake_requires_operator_or_steering_authority() -> None:
    conn = message_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET actor_id=10,mode='dash' WHERE session_id='s1'"
    )
    conn.commit()

    with pytest.raises(SessionError) as refused:
        request_manual_wake(
            conn,
            actor_id=10,
            caller_session_id="s1",
            session_id="s2",
            item_ref=None,
            prompt=None,
            now=NOW,
        )

    assert refused.value.code == "SESSION_CONTROL_AUTHORITY_REQUIRED"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0

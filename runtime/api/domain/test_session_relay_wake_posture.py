"""Posture-version CAS coverage for native wake claims."""

from __future__ import annotations

from datetime import timedelta

import yoke_core.domain.session_message_delivery as message_delivery
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.session_turn_posture import stamp_turn_posture
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


TARGET_SESSION_ID = "s4"


def _waiting_candidate(conn):
    stamp_turn_posture(
        conn,
        session_id=TARGET_SESSION_ID,
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (str(NOW), TARGET_SESSION_ID),
    )
    conn.commit()
    send_message(
        conn,
        actor_id=10,
        sender_session_id=TARGET_SESSION_ID,
        selector=selector(session_ids=[TARGET_SESSION_ID]),
        body="Opaque body remains in the inbox.",
        now=NOW - timedelta(minutes=11),
    )
    return wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1))[0]


def test_prompt_injection_lease_closes_the_waiting_wake_window(monkeypatch) -> None:
    conn = message_connection()
    candidate = _waiting_candidate(conn)
    posture_before = conn.execute(
        "SELECT turn_posture,turn_posture_at FROM harness_sessions WHERE session_id=?",
        (TARGET_SESSION_ID,),
    ).fetchone()
    monkeypatch.setattr(message_delivery, "utc_now", lambda: NOW + timedelta(seconds=2))

    hook = message_delivery.lease_for_hook(
        conn,
        session_id=TARGET_SESSION_ID,
        hook_event="UserPromptSubmit",
        limit=10,
    )
    claim = claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:00:03Z")

    assert hook is not None
    assert claim is None
    posture_after = conn.execute(
        "SELECT turn_posture,turn_posture_at FROM harness_sessions WHERE session_id=?",
        (TARGET_SESSION_ID,),
    ).fetchone()
    assert (
        tuple(posture_after)
        == tuple(posture_before)
        == (
            "waiting",
            "2026-08-22T15:59:59.000000Z",
        )
    )
    receipt = conn.execute(
        "SELECT injection_lease_id,wake_attempt_count FROM session_message_recipients"
    ).fetchone()
    assert tuple(receipt) == (hook["lease_id"], 0)
    assert (
        conn.execute(
            "SELECT GROUP_CONCAT(attempt_kind) FROM session_message_attempts"
        ).fetchone()[0]
        == "hook"
    )


def test_posture_timestamp_change_invalidates_a_selected_candidate() -> None:
    conn = message_connection()
    candidate = _waiting_candidate(conn)
    stamp_turn_posture(
        conn,
        session_id=TARGET_SESSION_ID,
        posture="running",
        observed_at=NOW + timedelta(seconds=2),
    )
    conn.commit()

    claim = claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:00:03Z")

    assert claim is None
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )

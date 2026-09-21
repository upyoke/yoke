"""A park outranks a lingering native pid for wake delivery."""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_jobs import claim_wake_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    ALPHA_WORKSPACE,
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    park_session,
    selector,
    stamp_activity,
)


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _heartbeat() -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id="machine:m4",
        actor_id=10,
        machine_id="m4",
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(1,),
    )


def _connect_relay(conn) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES (?,?,?,?,?,?,?,?,?,?,'active')",
        (
            "machine:m4",
            10,
            "m4",
            "relay-host",
            "0.1.1",
            '{"codex-cli": "0.148.0a15"}',
            "[1]",
            NOW_TEXT,
            NOW_TEXT,
            "2026-08-23T00:00:00Z",
        ),
    )
    conn.commit()


def test_a_parked_candidate_tells_the_relay_the_session_has_parked() -> None:
    conn = message_connection()
    _send(conn)
    park_session(conn)
    stamp_activity(conn, when=NOW + timedelta(seconds=1))
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1))[0]
    assert candidate["parked"] is True

    _connect_relay(conn)
    job = claim_wake_job(conn, _heartbeat(), now="2026-08-22T16:00:01Z")
    assert job is not None
    assert job.target_parked is True
    assert job.target_workspace == ALPHA_WORKSPACE


def test_a_parked_session_spent_by_native_hold_is_still_wakeable() -> None:
    """The deferral bound walks the receipt to max_wake_attempts.

    After that the pid hold was the only recovery, which is how a parked
    session that had already asked to be woken stayed unwakeable.
    """
    conn = message_connection()
    message_id = _send(conn)
    park_session(conn)
    limit = project_policy(conn, 1).max_wake_attempts
    conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count=?,"
        "wake_escalation=? WHERE message_id=?",
        (limit, NATIVE_TURN_RUNNING_RESULT, message_id),
    )
    conn.commit()
    stamp_activity(conn, when=NOW + timedelta(seconds=1))
    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1))
    assert [row["session_id"] for row in eligible] == [NATIVE_WAKE_SESSION_ID]
    assert eligible[0]["parked"] is True


def test_an_unparked_session_spent_by_native_hold_stays_at_the_limit() -> None:
    conn = message_connection()
    message_id = _send(conn)
    limit = project_policy(conn, 1).max_wake_attempts
    conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count=?,"
        "wake_escalation=? WHERE message_id=?",
        (limit, NATIVE_TURN_RUNNING_RESULT, message_id),
    )
    conn.commit()
    stamp_activity(conn, when=NOW + timedelta(minutes=11))
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

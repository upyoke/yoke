"""Mail addressed to an ended session is not delivered by recruiting another.

A successor cannot acknowledge another session's envelope, so a wake that
starts a new native cannot settle the receipt. The plane records why and
leaves the message pending for an explicit cancel.
"""

from __future__ import annotations

from datetime import timedelta

from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    park_session,
    selector,
)
from yoke_core.domain.session_message_ended_recipient import (
    RECIPIENT_ENDED_RESULT,
    cancel_recovery,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_turn_posture import stamp_turn_posture


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Do not recruit a successor for this envelope.",
        now=NOW,
    )["message_id"]


def _stop(conn) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()


def _attempt(conn, message_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT result_code, evidence FROM session_message_attempts "
        "WHERE message_id=? AND target_session_id=?",
        (message_id, NATIVE_WAKE_SESSION_ID),
    ).fetchone()
    assert row is not None
    return str(row[0]), str(row[1] or "")


def test_an_ended_session_is_not_wake_eligible_and_records_why() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _stop(conn)

    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []
    assert wake_eligible_recipients(conn, now=NOW + timedelta(days=7)) == []

    code, evidence = _attempt(conn, message_id)
    assert code == RECIPIENT_ENDED_RESULT
    assert cancel_recovery(message_id) in evidence
    # A second sweep must not manufacture another attempt or a wake job.
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == 1
    )


def test_a_waiting_ended_session_still_wakes() -> None:
    conn = message_connection()
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.commit()
    _send(conn)
    _stop(conn)

    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))
    assert [row["wake_mode"] for row in eligible] == [WakeMode.WAITING]
    assert eligible[0]["liveness"] == "ended"


def test_a_parked_ended_session_still_wakes() -> None:
    conn = message_connection()
    park_session(conn)
    _send(conn)
    _stop(conn)

    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))
    assert len(eligible) == 1
    assert eligible[0]["parked"] is True


def test_a_quiet_live_session_still_wakes() -> None:
    conn = message_connection()
    _send(conn)

    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))
    assert len(eligible) == 1
    assert eligible[0]["liveness"] != "ended"

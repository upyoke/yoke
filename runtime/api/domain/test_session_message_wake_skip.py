"""Unavailable native routes spend a bounded budget and tell their sender."""

from datetime import timedelta
import pytest
import json

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain import session_message_wake as wake
from runtime.api.domain.test_session_message_support import (
    NOW,
    NATIVE_WAKE_SESSION_ID,
    message_connection,
    selector,
)


@pytest.mark.parametrize("explicit", [False, True])
def test_unsupported_version_is_bounded_and_parks_a_notice_without_a_seat(
    monkeypatch, explicit
):
    monkeypatch.setattr(wake, "machine_surface_versions", lambda *a, **kw: {})
    conn = message_connection()
    conn.execute("UPDATE session_message_recipients SET executor_surface='codex-cli'")
    message = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Deliver or tell me the failure.",
        now=NOW,
    )["message_id"]
    # The session's original snapshot is authoritative for delivery qualification.
    conn.execute(
        "UPDATE session_message_recipients SET executor_version='0.120.0' "
        "WHERE message_id=?",
        (message,),
    )
    conn.commit()
    if explicit:
        conn.execute(
            "UPDATE session_message_recipients SET routing_snapshot=? WHERE message_id=?",
            (json.dumps({"explicit_stopped_wake": True}), message),
        )
        conn.commit()
    for minute in (11, 17, 23, 29):
        wake_eligible_recipients(conn, now=NOW + timedelta(minutes=minute))
    row = conn.execute(
        "SELECT wake_attempt_count,state FROM session_message_recipients "
        "WHERE message_id=?",
        (message,),
    ).fetchone()
    assert tuple(row) == (1 if explicit else 3, "pending")
    assert conn.execute(
        "SELECT COUNT(*) FROM session_message_attempts WHERE message_id=?",
        (message,),
    ).fetchone()[0] == (1 if explicit else 3)
    notices = conn.execute(
        "SELECT message_id,body FROM session_messages WHERE message_id<>? "
        "AND idempotency_key LIKE 'native-wake-failed:%'",
        (message,),
    ).fetchall()
    assert len(notices) == 1
    notice, body = notices[0]
    assert ("skipped_version" if explicit else "wake_attempts_exhausted") in body
    assert "surface_version_below_floor" in body
    assert f"yoke messages get {message}" in body
    assert (
        conn.execute(
            "SELECT session_id FROM session_message_recipients WHERE message_id=?",
            (notice,),
        ).fetchall()
        == []
    )
    assert (
        conn.execute(
            "SELECT actor_id FROM actor_message_recipients "
            "WHERE message_id=? AND recipient_kind='actor'",
            (notice,),
        ).fetchone()
        is None
    )
    steering = conn.execute(
        "SELECT seat_session_id, state FROM actor_message_recipients "
        "WHERE message_id=? AND recipient_kind='steering'",
        (notice,),
    ).fetchone()
    assert tuple(steering) == (None, "awaiting_seat")

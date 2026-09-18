"""A relay that left wake work behind is asked back before the next minute."""

from __future__ import annotations

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_wake_drain_cadence import (
    RELAY_DRAIN_POLL_SECONDS,
    wake_work_pending,
)
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE = "m4"
PROJECTS = (1,)


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _pending(conn, *, machine_id: str = MACHINE, projects=PROJECTS) -> bool:
    return wake_work_pending(
        conn, machine_id=machine_id, project_ids=projects, now=NOW_TEXT
    )


def test_a_quiet_machine_has_nothing_to_come_back_for() -> None:
    assert _pending(message_connection()) is False


def test_a_pending_receipt_pulls_the_relay_back() -> None:
    conn = message_connection()
    _send(conn)
    assert _pending(conn) is True
    # One second is the long-poll step the relay already re-checks on, so a
    # drain runs at the speed the relay was always willing to work at.
    assert RELAY_DRAIN_POLL_SECONDS == 1


def test_another_machine_is_never_pulled_back_for_this_work() -> None:
    """A relay is only recalled for jobs it is allowed to execute."""
    conn = message_connection()
    _send(conn)
    assert _pending(conn, machine_id="m9") is False
    assert _pending(conn, projects=(2,)) is False
    assert _pending(conn, projects=()) is False


def test_an_attempt_already_open_is_not_more_work() -> None:
    """The relay is executing that one; coming back finds nothing new."""
    conn = message_connection()
    message_id = _send(conn)
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at) "
        "VALUES ('a1',?,?,'wake_relay',?)",
        (message_id, NATIVE_WAKE_SESSION_ID, NOW_TEXT),
    )
    conn.commit()
    assert _pending(conn) is False


def test_work_still_ahead_of_its_wake_horizon_does_not_pull_anyone_back() -> None:
    conn = message_connection()
    _send(conn)
    later = (NOW + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE session_message_recipients SET wake_after=?", (later,))
    conn.commit()
    assert _pending(conn) is False


def test_a_cancelled_envelope_is_not_work() -> None:
    conn = message_connection()
    message_id = _send(conn)
    conn.execute(
        "UPDATE session_messages SET cancelled_at=? WHERE message_id=?",
        (NOW_TEXT, message_id),
    )
    conn.commit()
    assert _pending(conn) is False

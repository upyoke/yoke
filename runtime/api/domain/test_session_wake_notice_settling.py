"""A wake notice lives exactly as long as the absence it reports.

The notice is derived: it tells a desktop conversation's operator that a
message is waiting on a turn only they can take. Nothing tells the notice
when that stops being true — the hook runs, the seat acknowledges, the
message is cancelled or expires, the conversation ends — so the Inbox went
on asking for a wake that had already happened. These cover the settling
that closes that gap, and the two lines it must not cross: it withdraws
only the notices this path raised for the person reading, and it never
calls a still-pending message delivered just because that chat came back.
"""

from __future__ import annotations

from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_operator_wake_notice import (
    NOTICE_IDEMPOTENCY_PREFIX,
    settle_operator_wake_notices,
)
from runtime.api.domain.test_session_desktop_operator_wake import (
    CLAUDE_DESKTOP_SESSION_ID,
    STARVED,
    _add_desktop_session,
    _go_quiet,
    _operator_notices,
    _send_to,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


#: A tool call in the desktop chat after the message arrived.
RESUMED_TEXT = "2026-08-22T16:10:00Z"
OTHER_DESKTOP_SESSION_ID = "s-desktop-other"


def _standing_notice_count(conn, *, actor_id: int = 10) -> int:
    """Notices still presented to one operator, cancelled ones excluded."""
    return len(
        conn.execute(
            "SELECT m.message_id FROM actor_message_recipients r "
            "JOIN session_messages m ON m.message_id=r.message_id "
            "WHERE r.recipient_kind=? AND r.actor_id=? "
            "AND m.cancelled_at IS NULL AND m.idempotency_key LIKE ?",
            (ACTOR_KIND, actor_id, f"{NOTICE_IDEMPOTENCY_PREFIX}:%"),
        ).fetchall()
    )


def _notice_settlement(conn):
    row = conn.execute(
        "SELECT cancelled_at, cancellation_reason FROM session_messages "
        "WHERE idempotency_key LIKE ?",
        (f"{NOTICE_IDEMPOTENCY_PREFIX}:%",),
    ).fetchone()
    return None if row is None else dict(row)


def _standing_notice(conn) -> str:
    """Raise a notice for a starved desktop envelope and return its id."""
    _add_desktop_session(conn)
    message_id = _send_to(conn, CLAUDE_DESKTOP_SESSION_ID)
    _go_quiet(conn, CLAUDE_DESKTOP_SESSION_ID, when=STARVED)
    wake_eligible_recipients(conn, now=STARVED)
    assert _standing_notice_count(conn) == 1
    return message_id


def test_a_notice_settles_once_its_message_reaches_the_conversation() -> None:
    """The card asks for a wake; a delivered message needs none."""
    conn = message_connection()
    message_id = _standing_notice(conn)
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged' WHERE message_id=?",
        (message_id,),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _standing_notice_count(conn) == 0
    settlement = _notice_settlement(conn)
    assert settlement["cancelled_at"]
    assert settlement["cancellation_reason"] == "original_acknowledged"


def test_a_notice_settles_when_its_conversation_ends() -> None:
    conn = message_connection()
    _standing_notice(conn)
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, CLAUDE_DESKTOP_SESSION_ID),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _notice_settlement(conn)["cancellation_reason"] == "target_session_ended"


def test_a_notice_settles_when_its_message_is_cancelled() -> None:
    conn = message_connection()
    message_id = _standing_notice(conn)
    conn.execute(
        "UPDATE session_messages SET cancelled_at=? WHERE message_id=?",
        (NOW_TEXT, message_id),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _notice_settlement(conn)["cancellation_reason"] == "original_cancelled"


def test_a_notice_stands_while_its_message_is_still_waiting() -> None:
    conn = message_connection()
    _standing_notice(conn)

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 0
    assert _standing_notice_count(conn) == 1


def test_settling_leaves_an_unrelated_operator_message_alone() -> None:
    """Only notices this module raised are ever withdrawn."""
    conn = message_connection()
    message_id = _standing_notice(conn)
    grant_actor_org_role(conn, actor_id=10, org_id=1, role_name=ROLE_ADMIN)
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(actors=["10"]),
        body="Approve the production promotion when you are ready.",
        now=NOW,
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='acknowledged' WHERE message_id=?",
        (message_id,),
    )
    conn.commit()

    settle_operator_wake_notices(conn, actor_id=10, now=STARVED)

    remaining = _operator_notices(conn)
    assert len(remaining) == 1
    assert "Approve the production promotion" in remaining[0]


def test_a_resumed_chat_settles_the_notice_without_claiming_delivery() -> None:
    """A tool call after the send proves the person came back, nothing more.

    That is exactly what the notice asked for, so the ask retires — but the
    envelope is still pending on a delivery defect, and the settlement says
    so rather than recording a delivery that never happened.
    """
    conn = message_connection()
    message_id = _standing_notice(conn)
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=? WHERE session_id=?",
        (RESUMED_TEXT, CLAUDE_DESKTOP_SESSION_ID),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _notice_settlement(conn)["cancellation_reason"] == "conversation_resumed"

    receipt = dict(
        conn.execute(
            "SELECT state, acknowledged_at, injection_count "
            "FROM session_message_recipients WHERE message_id=?",
            (message_id,),
        ).fetchone()
    )
    assert receipt["state"] == "pending"
    assert receipt["acknowledged_at"] is None
    assert receipt["injection_count"] == 0


def test_an_injected_message_settles_as_the_delivery_it_is() -> None:
    conn = message_connection()
    message_id = _standing_notice(conn)
    conn.execute(
        "UPDATE session_message_recipients SET injection_count=1,last_injected_at=? "
        "WHERE message_id=?",
        (RESUMED_TEXT, message_id),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _notice_settlement(conn)["cancellation_reason"] == "original_injected"


def test_a_notice_settles_when_its_message_expires() -> None:
    conn = message_connection()
    message_id = _standing_notice(conn)
    conn.execute(
        "UPDATE session_messages SET expires_at=? WHERE message_id=?",
        (NOW_TEXT, message_id),
    )
    conn.commit()

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1
    assert _notice_settlement(conn)["cancellation_reason"] == "original_expired"


def test_one_persons_inbox_read_does_not_settle_anothers_notice() -> None:
    """Convergence is bounded by the Inbox being composed."""
    conn = message_connection()
    _add_desktop_session(conn, session_id=OTHER_DESKTOP_SESSION_ID)
    conn.execute(
        "UPDATE harness_sessions SET actor_id=11 WHERE session_id=?",
        (OTHER_DESKTOP_SESSION_ID,),
    )
    conn.commit()
    mine = _standing_notice(conn)
    theirs = _send_to(conn, OTHER_DESKTOP_SESSION_ID)
    _go_quiet(conn, OTHER_DESKTOP_SESSION_ID, when=STARVED)
    wake_eligible_recipients(conn, now=STARVED)
    for message_id in (mine, theirs):
        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged' "
            "WHERE message_id=?",
            (message_id,),
        )
    conn.commit()
    assert _standing_notice_count(conn, actor_id=11) == 1

    assert settle_operator_wake_notices(conn, actor_id=10, now=STARVED) == 1

    assert _standing_notice_count(conn, actor_id=10) == 0
    assert _standing_notice_count(conn, actor_id=11) == 1

"""A pending envelope still escalates once later activity stops.

Activity after the send once disqualified a receipt outright. The reading
was that a hook had run and declined to attach it, which is a delivery
defect rather than an absent route — true while the session keeps calling
tools, and wrong the moment it stops. These cover the shape that fell
through: a message arrives mid-flight, unrelated turns run their own hooks
without attaching it, the session exits cleanly, and the envelope is left
with no route and no escalation.
"""

from __future__ import annotations

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_starvation import (
    PARKED_WITHOUT_IDLE_WAKE,
    STARVED_HOOK_ROUTE,
)
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from runtime.api.domain.test_session_message_support import (
    ACK_GRACE,
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    park_session,
    selector,
    stamp_activity,
)


#: Two turns that ran after the send and attached nothing, the second of
#: them the clean exit the worker never came back from.
FIRST_LATER_TURN = NOW + timedelta(minutes=3)
LAST_LATER_TURN = NOW + timedelta(minutes=5)
#: A full silence window past that last turn.
ROUTE_ABSENT = LAST_LATER_TURN + ACK_GRACE + timedelta(seconds=1)


def _text(when) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _send(conn, body: str = "Correction the worker never read.") -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body=body,
        now=NOW,
    )["message_id"]


def test_a_recipient_that_stopped_after_the_send_still_escalates() -> None:
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=LAST_LATER_TURN, tool_call=_text(LAST_LATER_TURN))
    assert wake_eligible_recipients(conn, now=LAST_LATER_TURN) == []

    # The heartbeat keeps liveness reading active the whole time, which is
    # what made the envelope invisible: nothing else ever looked again.
    stamp_activity(conn, when=ROUTE_ABSENT, tool_call=_text(LAST_LATER_TURN))
    eligible = wake_eligible_recipients(conn, now=ROUTE_ABSENT)

    assert len(eligible) == 1
    assert eligible[0]["liveness"] == "active"
    assert eligible[0]["wake_escalation"] == STARVED_HOOK_ROUTE


def test_a_recipient_still_calling_tools_is_left_alone() -> None:
    """Working is the case the window exists to protect.

    Each new tool call moves the silence window forward, so a session whose
    hooks are running is never escalated however long the envelope waits.
    """
    conn = message_connection()
    _send(conn)
    for minute in range(1, 20):
        ticking = NOW + timedelta(minutes=minute)
        stamp_activity(conn, when=ticking, tool_call=_text(ticking))
        assert wake_eligible_recipients(conn, now=ticking) == []


def test_every_pending_envelope_to_the_stopped_recipient_escalates() -> None:
    """The absence is the session's, so it covers all of its mail."""
    conn = message_connection()
    first = _send(conn, "First correction.")
    stamp_activity(conn, when=FIRST_LATER_TURN, tool_call=_text(FIRST_LATER_TURN))
    second = send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Second correction, after the turn that ignored the first.",
        now=FIRST_LATER_TURN,
    )["message_id"]
    stamp_activity(conn, when=LAST_LATER_TURN, tool_call=_text(LAST_LATER_TURN))

    stamp_activity(conn, when=ROUTE_ABSENT, tool_call=_text(LAST_LATER_TURN))
    eligible = wake_eligible_recipients(conn, now=ROUTE_ABSENT)

    assert sorted(row["message_id"] for row in eligible) == sorted([first, second])
    assert {row["wake_escalation"] for row in eligible} == {STARVED_HOOK_ROUTE}


def test_a_recipient_that_has_never_called_a_tool_waits_from_the_send() -> None:
    """With no tool call to measure, the envelope's own arrival is the start."""
    conn = message_connection()
    _send(conn)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=?,last_tool_call_at=NULL "
        "WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    early = NOW + ACK_GRACE - timedelta(seconds=1)
    assert wake_eligible_recipients(conn, now=early) == []

    starved = NOW + ACK_GRACE + timedelta(seconds=1)
    eligible = wake_eligible_recipients(conn, now=starved)

    assert [row["wake_escalation"] for row in eligible] == [STARVED_HOOK_ROUTE]


def test_a_recipient_parked_after_the_send_needs_no_grace_window() -> None:
    """Parking declares the absence; earlier activity does not undo it."""
    conn = message_connection()
    _send(conn)
    stamp_activity(conn, when=FIRST_LATER_TURN, tool_call=_text(FIRST_LATER_TURN))
    park_session(conn)

    eligible = wake_eligible_recipients(conn, now=FIRST_LATER_TURN)

    assert [row["wake_escalation"] for row in eligible] == [PARKED_WITHOUT_IDLE_WAKE]


def test_a_desktop_recipient_that_stopped_is_never_resumed() -> None:
    """Its operator's window is the one route, whatever the clocks say."""
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Correction to a conversation Yoke may not open.",
        now=NOW,
    )
    stamp_activity(
        conn,
        when=LAST_LATER_TURN,
        tool_call=_text(LAST_LATER_TURN),
        session_id="s1",
    )
    stamp_activity(
        conn,
        when=ROUTE_ABSENT,
        tool_call=_text(LAST_LATER_TURN),
        session_id="s1",
    )

    assert wake_eligible_recipients(conn, now=ROUTE_ABSENT) == []

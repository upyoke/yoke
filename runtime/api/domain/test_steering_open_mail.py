"""Only open steering mail is actionable, and each waiting message is named.

A role-addressed message is open while its message is neither cancelled
nor expired. Lists, handoff candidates and the message detail all apply
that one rule, and the fleet's awaiting-seat section names every open
message with its item and the seat scope that covers it.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_core.domain import session_message_page, session_message_queries
from yoke_core.domain.session_message_queries import get_message
from yoke_core.domain.session_message_receipts import cancel_message
from yoke_core.domain.steering_fleet_report_awaiting_seat import (
    awaiting_seat_lines,
    read_awaiting_seat,
)
from yoke_core.domain.steering_message_drain import drain_to_seat
from yoke_core.domain.steering_message_recipients import (
    STATE_DELIVERED,
    awaiting_seat_rows,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    page_rows,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    PROJECT_SCOPE,
    _end,
    _say_steering,
    _seat,
    _steering_row,
)


#: Past the default message lifetime of mail sent at ``NOW``.
LATER = NOW + timedelta(hours=25)


@pytest.fixture
def read_at(monkeypatch):
    def pin(when) -> None:
        monkeypatch.setattr(session_message_page, "utc_now", lambda: when)
        monkeypatch.setattr(session_message_queries, "utc_now", lambda: when)

    return pin


def _listed(conn, state: str) -> list[str]:
    rows = page_rows(conn, actor_id=11, caller_session_id=None, state=state)
    return [row["message_id"] for row in rows]


def _waiting(conn, now=NOW) -> list[str]:
    rows = awaiting_seat_rows(conn, project_id=1, scope=PROJECT_SCOPE, now=now)
    return [str(row["message_id"]) for row in rows]


def test_a_cancelled_steering_message_leaves_every_open_read(read_at) -> None:
    read_at(NOW)
    conn = message_connection()
    sent = _say_steering(conn)
    cancel_message(conn, message_id=sent["message_id"], actor_id=10, now=NOW)

    assert _listed(conn, "unacknowledged") == []
    assert _listed(conn, "pending") == []
    assert _listed(conn, "expired") == [sent["message_id"]]
    assert _waiting(conn) == []


def test_an_expired_steering_message_settles_in_list_candidates_and_detail(
    read_at,
) -> None:
    conn = message_connection()
    sent = _say_steering(conn)
    read_at(NOW)
    assert _listed(conn, "unacknowledged") == [sent["message_id"]]
    assert _waiting(conn) == [sent["message_id"]]

    read_at(LATER)

    assert _listed(conn, "unacknowledged") == []
    assert _listed(conn, "expired") == [sent["message_id"]]
    assert _waiting(conn, now=LATER) == []
    handoff = drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s4",
        claim_id=11,
        descriptor="alpha",
        now=LATER,
    )
    assert handoff["drained_count"] == 0
    recipient = get_message(
        conn, message_id=sent["message_id"], actor_id=10, session_id="s1"
    )["steering_recipient"]
    assert recipient["state"] == "expired"
    assert "nothing is owed" in recipient["summary"]


def test_the_awaiting_line_names_message_item_seat_and_acquire() -> None:
    conn = message_connection()
    sent = _say_steering(conn)

    entries = read_awaiting_seat(
        conn, project_id=1, scope=PROJECT_SCOPE, session_id="s9", now=NOW
    )
    heading, line = awaiting_seat_lines(entries)

    assert heading.startswith("1 steering message(s) awaiting a seat")
    assert line == (
        f"  {sent['message_id']}  ALP-1  alpha  take the seat: "
        "yoke claims steering acquire --project 1"
    )


def test_a_held_scope_names_the_message_without_acquire_advice() -> None:
    conn = message_connection()
    sent = _say_steering(conn)
    _seat(conn, claim_id=12, session_id="s4")

    entries = read_awaiting_seat(
        conn, project_id=1, scope=PROJECT_SCOPE, session_id="s4", now=NOW
    )
    _, line = awaiting_seat_lines(entries)

    assert "held by this session" in line
    assert "acquire" not in line
    assert line.endswith(f"read: yoke messages get {sent['message_id']}")


def test_a_seat_released_before_its_session_ended_hands_mail_to_the_successor() -> None:
    """The production sequence behind three rows left with an ended seat.

    The old seat released its claim, the successor acquired four minutes
    later, and the old session ended twenty minutes after that. The drain
    read the still-running session as a live seat, so it skipped the mail,
    and nothing re-drained once that session ended.
    """
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    held = _say_steering(conn)
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=10", (NOW_TEXT,))
    conn.commit()

    assert _waiting(conn) == [held["message_id"]]

    _seat(conn, claim_id=11, session_id="s4")
    handoff = drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s4",
        claim_id=11,
        descriptor="alpha",
        now=NOW,
    )
    conn.commit()

    assert handoff["drained_count"] == 1
    assert handoff["stranded_count"] == 1
    assert "held by seat s2 that ended or released" in handoff["digest"]
    row = _steering_row(conn, held["message_id"])
    assert (row["state"], row["seat_session_id"]) == (STATE_DELIVERED, "s4")
    _end(conn, "s2")
    assert _waiting(conn) == []


def test_a_live_seat_still_holding_its_claim_keeps_its_mail() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _say_steering(conn)

    assert _waiting(conn) == []

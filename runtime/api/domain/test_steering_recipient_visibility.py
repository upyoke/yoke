"""What a role-addressed message's own recipient looks like to a reader.

A message addressed to the steering role has a durable recipient whether or
not a session is holding it, and every read surface owes the sender that
fact. Describing delivery only in terms of sessions is what made a message
that parked correctly report zero recipients and nothing else — the same
answer a message that reached nobody would give. These cover the recipient
each surface renders: its state, the scope it belongs to, and the seat when
one holds it.
"""

from __future__ import annotations

from yoke_core.domain.session_message_queries import get_message, list_messages
from yoke_core.domain.session_message_service import preview_message
from yoke_core.domain.steering_message_drain import drain_to_seat
from yoke_core.domain.steering_message_recipients import (
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    awaiting_seat_count,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    PROJECT_SCOPE,
    _say_steering,
    _seat,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


def test_preview_reports_the_scope_and_whether_it_would_park() -> None:
    conn = message_connection()

    preview = preview_message(
        conn,
        actor_id=10,
        selector=selector(steering=True),
        sender_session_id="s1",
        now=NOW,
    )

    recipient = preview["steering_recipient"]
    assert recipient["scope"] == PROJECT_SCOPE
    assert recipient["state"] == STATE_AWAITING_SEAT
    assert recipient["session_id"] is None
    assert "queued for the steering seat" in recipient["summary"]
    assert preview["recipient_count"] == 1


def test_a_parked_send_reports_the_seat_it_is_queued_for() -> None:
    """Zero live sessions is a queued recipient, not a delivery failure."""
    conn = message_connection()

    sent = _say_steering(conn)

    assert sent["recipients"] == []
    recipient = sent["steering_recipient"]
    assert recipient["state"] == STATE_AWAITING_SEAT
    assert recipient["scope"] == PROJECT_SCOPE
    assert recipient["sender_item_id"] == 101
    assert "alpha" in recipient["scope_label"]
    assert "queued for the steering seat" in recipient["summary"]
    assert sent["recipient_count"] == 1


def test_a_seated_send_names_the_seat_holding_it() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    sent = _say_steering(conn)

    recipient = sent["steering_recipient"]
    assert recipient["state"] == STATE_DELIVERED
    assert recipient["session_id"] == "s2"
    assert "delivered to the steering seat" in recipient["summary"]


def test_reading_a_role_addressed_message_carries_its_recipient_state() -> None:
    conn = message_connection()
    sent = _say_steering(conn)

    detail = get_message(
        conn,
        message_id=sent["message_id"],
        actor_id=10,
        session_id="s1",
    )

    assert detail["steering_recipient"]["state"] == STATE_AWAITING_SEAT
    assert detail["steering_recipient"]["scope"] == PROJECT_SCOPE


def test_a_seat_lists_the_role_addressed_mail_it_holds() -> None:
    """A drained report reaches its seat through the role row, not a session."""
    conn = message_connection()
    sent = _say_steering(conn)
    _seat(conn, claim_id=11, session_id="s2")
    drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s2",
        claim_id=11,
        descriptor="alpha",
        now=NOW,
    )
    conn.commit()

    listed = list_messages(
        conn,
        actor_id=10,
        caller_session_id="s2",
        session_id="s2",
    )

    assert [row["message_id"] for row in listed] == [sent["message_id"]]
    assert listed[0]["steering_recipient"]["session_id"] == "s2"


def test_a_project_seat_inherits_a_report_no_document_covers() -> None:
    """The coverage difference a project-level seat is acquired for.

    A seat narrowed to the standing plan covers only what is linked to it,
    so a report from an unlinked item — the ordinary case for work filed
    without a document — reaches nobody until a project-wide seat takes it.
    """
    conn = message_connection()
    _say_steering(conn)
    plan_scope = {"project_id": 1, "document": "CURRENT-PLAN"}

    assert awaiting_seat_count(conn, project_id=1, scope=plan_scope) == 0
    assert awaiting_seat_count(conn, project_id=1, scope=PROJECT_SCOPE) == 1

    _seat(conn, claim_id=12, session_id="s2")
    handoff = drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s2",
        claim_id=12,
        descriptor="alpha",
        now=NOW,
    )
    conn.commit()

    assert handoff["drained_count"] == 1

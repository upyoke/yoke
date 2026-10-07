"""A document seat takes parked mail from linked items in any project.

A role-addressed row is filed under the sender item's own project. A
document seat belongs to the document's owning project but covers every
item linked to that document, so an item in another project that is linked
to the document parks its report under a project the seat does not own.
These tests pin that the seat still drains and counts that mail, and that
the sender project's own seat still leaves it alone.
"""

from __future__ import annotations

from runtime.api.domain.test_session_message_support import (
    IDLE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.steering_message_drain import drain_to_seat
from yoke_core.domain.steering_message_recipients import (
    STATE_ACKNOWLEDGED,
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    awaiting_seat_count,
)


DOCUMENT_SCOPE = {"project_id": 1, "document": "AREA-PLAN"}
SENDER_PROJECT_SCOPE = {"project_id": 2}
OTHER_DOCUMENT_SCOPE = {"project_id": 1, "document": "OTHER-PLAN"}
LINKED_ITEM = 201
SENDER = IDLE_WAKE_SESSION_ID
SEAT = "s2"


def _cross_project_report(conn) -> str:
    """Project 2's item, linked to project 1's document, reports with no seat."""
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (40,?,'item',?,?)",
        (SENDER, f'{{"item_id":{LINKED_ITEM}}}', NOW_TEXT),
    )
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) VALUES (?,1,?,?)",
        (LINKED_ITEM, DOCUMENT_SCOPE["document"], NOW_TEXT),
    )
    conn.commit()
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id=SENDER,
        selector=selector(steering=True),
        body="DONE BET-1 the linked change landed.",
        now=NOW,
    )
    return str(sent["message_id"])


def _row(conn, message_id: str) -> dict:
    found = conn.execute(
        "SELECT state, project_id, seat_session_id FROM actor_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    return dict(found)


def _drain(conn, scope: dict, *, session_id: str = SEAT, claim_id: int = 50):
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'steering',?,?)",
        (claim_id, session_id, str(scope).replace("'", '"'), NOW_TEXT),
    )
    handoff = drain_to_seat(
        conn,
        scope=scope,
        project_id=int(scope["project_id"]),
        session_id=session_id,
        claim_id=claim_id,
        descriptor="seat",
        now=NOW,
    )
    conn.commit()
    return handoff


def test_the_report_parks_under_the_sender_items_project() -> None:
    conn = message_connection()
    message_id = _cross_project_report(conn)

    assert _row(conn, message_id) == {
        "state": STATE_AWAITING_SEAT,
        "project_id": 2,
        "seat_session_id": None,
    }


def test_the_document_seat_counts_and_drains_linked_mail_from_another_project() -> None:
    conn = message_connection()
    message_id = _cross_project_report(conn)

    assert awaiting_seat_count(conn, project_id=1, scope=DOCUMENT_SCOPE) == 1
    handoff = _drain(conn, DOCUMENT_SCOPE)

    assert handoff["drained_count"] == 1
    assert handoff["parked_count"] == 1
    assert "the linked change landed" in handoff["digest"]
    assert _row(conn, message_id)["state"] == STATE_DELIVERED
    assert _row(conn, message_id)["seat_session_id"] == SEAT
    assert awaiting_seat_count(conn, project_id=1, scope=DOCUMENT_SCOPE) == 0

    acknowledge_message(conn, message_id=message_id, session_id=SEAT, now=NOW)
    conn.commit()
    assert _row(conn, message_id)["state"] == STATE_ACKNOWLEDGED


def test_the_sender_projects_seat_does_not_take_document_linked_mail() -> None:
    conn = message_connection()
    message_id = _cross_project_report(conn)

    assert awaiting_seat_count(conn, project_id=2, scope=SENDER_PROJECT_SCOPE) == 0
    handoff = _drain(conn, SENDER_PROJECT_SCOPE)

    assert handoff["drained_count"] == 0
    assert _row(conn, message_id)["state"] == STATE_AWAITING_SEAT


def test_another_document_seat_in_the_owning_project_does_not_take_it() -> None:
    conn = message_connection()
    message_id = _cross_project_report(conn)

    assert awaiting_seat_count(conn, project_id=1, scope=OTHER_DOCUMENT_SCOPE) == 0
    assert awaiting_seat_count(conn, project_id=1, scope={"project_id": 1}) == 0
    assert _drain(conn, OTHER_DOCUMENT_SCOPE)["drained_count"] == 0
    assert _row(conn, message_id)["state"] == STATE_AWAITING_SEAT

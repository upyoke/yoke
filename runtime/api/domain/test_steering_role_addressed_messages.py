"""Addressing the steering role: parking, seating, draining, acknowledging."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_service import preview_message, send_message
from yoke_core.domain.session_message_steering import ADDRESS_UNRESOLVED_CODE
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.steering_message_drain import DIGEST_BEGIN, drain_to_seat
from yoke_core.domain.steering_message_recipients import (
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    drainable_rows,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


BODY = "Blocked: the merge gate went red on the schema converge step."
DONE_BODY = "DONE ALP-1 close-out reporting landed."
PROJECT_SCOPE = {"project_id": 1}


def _seat(conn, *, claim_id: int, session_id: str, scope: str = '{"project_id":1}'):
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'steering',?,?)",
        (claim_id, session_id, scope, NOW_TEXT),
    )
    conn.commit()


def _end(conn, session_id: str) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, session_id),
    )
    conn.commit()


def _say_steering(conn, *, sender="s1", body=BODY, **selector_values):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id=sender,
        selector=selector(steering=True, **selector_values),
        body=body,
        now=NOW,
    )


def _release_item_claim(conn, claim_id: int = 1) -> None:
    """Close-out releases the item claim before the report is written."""
    conn.execute(
        "UPDATE work_claims SET released_at=? WHERE id=?", (NOW_TEXT, claim_id)
    )
    conn.commit()


def _message_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0])


def _steering_row(conn, message_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM actor_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()
    return dict(row)


def test_a_held_item_addresses_the_seat_covering_its_project() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    sent = _say_steering(conn)

    assert [r["session_id"] for r in sent["recipients"]] == ["s2"]
    row = _steering_row(conn, sent["message_id"])
    assert row["recipient_kind"] == "steering"
    assert row["state"] == STATE_DELIVERED
    assert row["seat_session_id"] == "s2"
    assert row["seat_claim_id"] == 10
    assert row["sender_item_id"] == 101
    assert row["project_id"] == 1


def test_no_live_seat_parks_the_message_instead_of_refusing() -> None:
    conn = message_connection()

    sent = _say_steering(conn)

    assert sent["recipient_count"] == 0
    row = _steering_row(conn, sent["message_id"])
    assert row["state"] == STATE_AWAITING_SEAT
    assert row["seat_session_id"] is None


def test_an_ended_seat_parks_rather_than_routing_into_a_dead_session() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _end(conn, "s2")

    sent = _say_steering(conn)

    assert sent["recipient_count"] == 0
    assert _steering_row(conn, sent["message_id"])["state"] == STATE_AWAITING_SEAT


def test_a_sender_that_never_held_an_item_must_name_the_scope() -> None:
    conn = message_connection()

    with pytest.raises(SessionMessageError) as raised:
        _say_steering(conn, sender="s2")

    assert raised.value.code == ADDRESS_UNRESOLVED_CODE
    assert "--steering-scope" in str(raised.value)


def test_close_out_releasing_the_claim_still_addresses_the_seat() -> None:
    """The DONE report is written once the item claim is already gone."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s4")
    _release_item_claim(conn)

    sent = _say_steering(conn, body=DONE_BODY)

    assert [r["session_id"] for r in sent["recipients"]] == ["s4"]
    assert _steering_row(conn, sent["message_id"])["sender_item_id"] == 101


def test_one_terminal_report_per_item_reaches_the_seat_once() -> None:
    """A reworded retry of the same DONE is the same report, not a second one."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s4")
    _release_item_claim(conn)

    first = _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=f"{DONE_BODY} Merged and green.")

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    assert _message_count(conn) == 1


def test_a_second_substantive_update_is_not_a_terminal_report() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s4")

    first = _say_steering(conn)
    second = _say_steering(conn, body="Blocked: the queue rejected the rebase.")

    assert second["message_id"] != first["message_id"]
    assert _message_count(conn) == 2


def test_an_explicit_scope_addresses_a_seat_without_a_held_item() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    sent = _say_steering(conn, sender="s4", steering_scope=PROJECT_SCOPE)

    assert [r["session_id"] for r in sent["recipients"]] == ["s2"]
    assert _steering_row(conn, sent["message_id"])["sender_item_id"] is None


def test_preview_reports_the_scope_and_whether_it_would_park() -> None:
    conn = message_connection()

    preview = preview_message(
        conn,
        actor_id=10,
        selector=selector(steering=True),
        sender_session_id="s1",
        now=NOW,
    )

    assert preview["steering_scope"] == PROJECT_SCOPE
    assert preview["parked"] is True


def test_acquiring_the_scope_drains_parked_and_stranded_mail() -> None:
    conn = message_connection()
    parked = _say_steering(conn, body="Blocked: nobody was steering when I asked.")
    _seat(conn, claim_id=10, session_id="s2")
    stranded = _say_steering(conn, body="Blocked: the seat that took this then ended.")
    _end(conn, "s2")
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=10", (NOW_TEXT,))
    conn.commit()

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

    assert handoff["drained_count"] == 2
    assert handoff["parked_count"] == 1
    assert handoff["stranded_count"] == 1
    assert handoff["digest"].startswith(DIGEST_BEGIN)
    assert "ALP-1" in handoff["digest"]
    assert "nobody was steering" in handoff["digest"]
    assert "the seat that took this then ended" in handoff["digest"]
    for sent in (parked, stranded):
        row = _steering_row(conn, sent["message_id"])
        assert row["state"] == STATE_DELIVERED
        assert row["seat_session_id"] == "s4"
        assert row["seat_claim_id"] == 11


def test_a_seat_that_answered_before_ending_leaves_nothing_to_drain() -> None:
    """Re-handing an answered question would ask for the answer twice."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _say_steering(conn)
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Take the schema converge fix and rerun the gate.",
        now=NOW + timedelta(minutes=1),
    )
    _end(conn, "s2")

    assert drainable_rows(conn, scope=PROJECT_SCOPE, project_id=1) == []


def test_a_live_seat_keeps_its_own_mail() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _say_steering(conn)

    assert drainable_rows(conn, scope=PROJECT_SCOPE, project_id=1) == []


def test_the_seat_acknowledging_records_it_on_the_role_row() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    sent = _say_steering(conn)

    acknowledge_message(conn, message_id=sent["message_id"], session_id="s2", now=NOW)

    assert _steering_row(conn, sent["message_id"])["state"] == "acknowledged"


def test_a_scope_in_another_project_is_not_drained() -> None:
    conn = message_connection()
    _say_steering(conn)

    assert drainable_rows(conn, scope={"project_id": 2}, project_id=2) == []

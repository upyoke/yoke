"""Actionable-first Fleet message list paging and visibility."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_page import read_message_page
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    PROJECT_SCOPE,
    _say_steering,
    _seat,
)


@pytest.fixture(autouse=True)
def _fixed_delivery_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery, session_message_page

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)
    monkeypatch.setattr(session_message_page, "utc_now", lambda: NOW)


def _message(
    conn,
    *,
    session_id: str,
    offset: int,
    settled: bool,
) -> str:
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[session_id]),
        body=f"message {offset}",
        now=NOW + timedelta(minutes=offset),
    )
    message_id = sent["message_id"]
    if settled:
        conn.execute(
            "UPDATE session_message_recipients SET state='acknowledged',"
            "acknowledged_at=? WHERE message_id=?",
            ((NOW + timedelta(minutes=offset)).isoformat(), message_id),
        )
        conn.commit()
    return message_id


def test_more_than_one_hundred_other_project_rows_cannot_hide_actionable() -> None:
    conn = message_connection()
    actionable_id = _message(conn, session_id="s1", offset=0, settled=False)
    for offset in range(1, 102):
        _message(conn, session_id="s3", offset=offset, settled=True)

    page = read_message_page(
        conn,
        actor_id=10,
        caller_session_id="s2",
        projects=[1],
    )

    assert page["actionable_count"] == 1
    assert page["settled_matched_count"] == 0
    assert [row["message_id"] for row in page["messages"]] == [actionable_id]


def test_settled_history_pages_by_stable_cursor_without_repeating_rows() -> None:
    conn = message_connection()
    for offset in range(1, 57):
        _message(conn, session_id="s3", offset=offset, settled=True)

    first = read_message_page(
        conn,
        actor_id=10,
        caller_session_id="s2",
        projects=[2],
    )
    first_ids = [row["message_id"] for row in first["messages"]]
    assert len(first_ids) == 50
    assert first["settled_matched_count"] == 56
    assert first["next_cursor"]

    newer_id = _message(conn, session_id="s3", offset=100, settled=True)
    second = read_message_page(
        conn,
        actor_id=10,
        caller_session_id="s2",
        projects=[2],
        cursor=first["next_cursor"],
    )
    second_ids = [row["message_id"] for row in second["messages"]]
    assert len(second_ids) == 6
    assert set(first_ids).isdisjoint(second_ids)
    assert newer_id not in second_ids
    assert second["next_cursor"] is None


def test_default_page_serves_one_compact_row_per_message() -> None:
    conn = message_connection()
    message_id = _message(conn, session_id="s1", offset=1, settled=False)

    visible = read_message_page(
        conn,
        actor_id=11,
        caller_session_id=None,
        projects=[1],
    )

    assert visible["detail"] == "summary"
    row = visible["messages"][0]
    assert row["message_id"] == message_id
    assert row["recipient_count"] == 1
    assert row["recipient_states"] == ["pending"]
    assert row["body_read"] == f"yoke messages get {message_id}"
    # The prose and the per-recipient receipts are what the row exists to
    # leave behind; `yoke messages get` still serves them whole.
    for dropped in ("body", "recipients", "actor_recipients", "attempts"):
        assert dropped not in row


def test_full_detail_still_serves_bodies_and_trimmed_recipient_rows() -> None:
    conn = message_connection()
    message_id = _message(conn, session_id="s1", offset=1, settled=False)

    visible = read_message_page(
        conn,
        actor_id=11,
        caller_session_id=None,
        projects=[1],
        detail="full",
    )

    assert visible["detail"] == "full"
    message = visible["messages"][0]
    assert message["message_id"] == message_id
    assert message["body"]
    assert "attempts" not in message
    recipient = message["recipients"][0]
    assert recipient["executor_surface"] == "codex-desktop"
    assert "routing_snapshot" not in recipient
    assert "resolution_evidence" not in recipient


def test_actor_visibility_is_enforced_before_the_projection() -> None:
    conn = message_connection()
    _message(conn, session_id="s1", offset=1, settled=False)

    hidden = read_message_page(
        conn,
        actor_id=13,
        caller_session_id=None,
        projects=[1],
    )

    assert hidden["messages"] == []
    assert hidden["actionable_count"] == 0


def test_invalid_settled_cursor_names_the_recovery() -> None:
    conn = message_connection()

    with pytest.raises(SessionMessageError) as raised:
        read_message_page(
            conn,
            actor_id=10,
            caller_session_id="s2",
            cursor="not-a-message-cursor",
        )

    assert raised.value.code == "cursor_invalid"
    assert "clear it" in str(raised.value)


def test_page_counts_a_parked_steering_message_as_actionable() -> None:
    """A role-addressed row with no seat is still open mail, not settled."""
    conn = message_connection()
    sent = _say_steering(conn)

    page = read_message_page(
        conn, actor_id=11, caller_session_id=None, state="unacknowledged"
    )

    assert page["actionable_count"] == 1
    assert [row["message_id"] for row in page["messages"]] == [sent["message_id"]]
    assert page["messages"][0]["needs_attention"] is True


def test_page_counts_a_row_delivered_by_drain_as_actionable() -> None:
    """``hand_to_seat`` never writes a session recipient for the new seat."""
    conn = message_connection()
    sent = _say_steering(conn)
    _seat(conn, claim_id=11, session_id="s4")
    from yoke_core.domain.steering_message_drain import drain_to_seat

    drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s4",
        claim_id=11,
        descriptor="alpha",
        now=NOW,
    )
    conn.commit()

    page = read_message_page(
        conn, actor_id=11, caller_session_id=None, state="unacknowledged"
    )

    assert page["actionable_count"] == 1
    assert [row["message_id"] for row in page["messages"]] == [sent["message_id"]]


def test_an_expired_steering_message_reads_settled_not_actionable(monkeypatch) -> None:
    """A steering row cannot itself carry ``expired``; the message's own
    expiry is what must settle it once nobody can act on it anymore."""
    from datetime import timedelta as _timedelta

    from yoke_core.domain import session_message_page

    conn = message_connection()
    sent = _say_steering(conn)

    monkeypatch.setattr(
        session_message_page, "utc_now", lambda: NOW + _timedelta(hours=25)
    )
    page = read_message_page(
        conn, actor_id=11, caller_session_id=None, state="unacknowledged"
    )

    assert page["actionable_count"] == 0
    assert [row["message_id"] for row in page["messages"]] == [sent["message_id"]]
    assert page["messages"][0]["needs_attention"] is False

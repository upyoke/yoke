"""Distinct parties across send, read, mailbox and seat handover."""

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_list_row import message_list_row
from yoke_core.domain.session_message_page_rows import page_summaries
from yoke_core.domain.session_message_queries import get_message
from yoke_core.domain.session_message_recipient_summary import recipient_summary
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_service import preview_message
from yoke_core.domain.steering_message_drain import drain_to_seat
from runtime.api.domain.session_message_support_test_support import (
    NOW, NOW_TEXT, message_connection, selector,
)
from runtime.api.domain.steering_role_addressed_messages_test_support import (
    PROJECT_SCOPE, _end, _say_steering, _seat,
)


@pytest.mark.parametrize("seated", [True, False])
def test_steering_party_is_counted_once_on_every_summary(monkeypatch, seated):
    from yoke_core.domain import session_message_queries

    monkeypatch.setattr(session_message_queries, "utc_now", lambda: NOW)
    conn = message_connection()
    if seated:
        _seat(conn, claim_id=10, session_id="s2")
    preview = preview_message(
        conn, actor_id=10, sender_session_id="s1",
        selector=selector(steering=True), now=NOW,
    )
    sent = _say_steering(conn)
    message_id = sent["message_id"]
    full = get_message(conn, message_id=message_id, actor_id=10, session_id="s1")
    page = page_summaries(conn, [message_id], now=NOW)[message_id]
    for summary in [preview, sent, full, page, message_list_row(page)]:
        assert summary["recipient_count"] == 1
        assert sum(summary["recipient_state_counts"].values()) == 1
    assert full["steering_recipient"]["scope"] == PROJECT_SCOPE
    assert full["steering_recipient"]["session_id"] == ("s2" if seated else None)
    expected = {"pending": 1} if seated else {"awaiting_seat": 1}
    assert full["recipient_state_counts"] == expected
    if seated:
        acknowledge_message(conn, message_id=message_id, session_id="s2", now=NOW)
        read = get_message(conn, message_id=message_id, actor_id=10, session_id="s1")
        assert read["recipient_state_counts"] == {"acknowledged": 1}
    expired = page_summaries(conn, [message_id], now=NOW + timedelta(hours=25))
    assert expired[message_id]["recipient_state_counts"] == (
        {"acknowledged": 1} if seated else {"expired": 1}
    )


def test_handover_counts_old_cancelled_party_and_new_party_once():
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    sent = _say_steering(conn)
    _end(conn, "s2")
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=10", (NOW_TEXT,))
    conn.commit()
    _seat(conn, claim_id=11, session_id="s4")
    drain_to_seat(
        conn, scope=PROJECT_SCOPE, project_id=1, session_id="s4",
        claim_id=11, descriptor="alpha", now=NOW,
    )
    conn.commit()
    page = page_summaries(conn, [sent["message_id"]], now=NOW)[sent["message_id"]]
    assert page["recipient_count"] == 2
    assert page["recipient_state_counts"] == {"cancelled": 1, "pending": 1}
    assert page["steering_recipient"]["session_id"] == "s4"
    assert message_list_row(page)["recipient_state_counts"] == page["recipient_state_counts"]


def test_unmatched_seat_and_human_remain_distinct_parties():
    message = {
        "recipients": [{"session_id": "old", "state": "cancelled"}],
        "actor_recipients": [{"actor_id": 10, "state": "pending"}],
        "steering_recipient": {"session_id": "new", "state": "delivered"},
    }
    assert recipient_summary(message) == {
        "recipient_count": 3,
        "recipient_states": ["cancelled", "delivered", "pending"],
        "recipient_state_counts": {"cancelled": 1, "pending": 1, "delivered": 1},
    }

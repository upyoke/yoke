"""A queued wake nothing attempted must not refuse the next wake forever."""

from __future__ import annotations

from datetime import timedelta

from yoke_core.domain.session_manual_wake import (
    QUEUED_WAKE_RELEASE_REASON,
    request_session_wake,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_wake_idempotency import stale_queued_wakes
from yoke_contracts.session_control.models import RecipientSelector
from runtime.api.domain.test_session_message_support import (
    ACK_GRACE,
    NOW,
    message_connection,
)


PAST_THE_WINDOW = NOW + ACK_GRACE + timedelta(seconds=1)


def _queued_wake(conn, *, idempotency_key: str = "first-wake") -> dict:
    return request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=None,
        idempotency_key=idempotency_key,
        now=NOW,
    )


def test_unattempted_queued_wake_past_its_window_is_released_for_a_retry() -> None:
    conn = message_connection()
    first = _queued_wake(conn)

    second = request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=None,
        idempotency_key="second-wake",
        now=PAST_THE_WINDOW,
    )

    assert second["message_id"] != first["message_id"]
    assert second["released_queued_wakes"] == [first["message_id"]]
    released = message_details(conn, first["message_id"])
    assert released["cancelled_at"]
    assert released["cancellation_reason"] == QUEUED_WAKE_RELEASE_REASON
    assert released["recipients"][0]["state"] == "cancelled"


def test_queued_wake_inside_its_window_is_still_in_flight() -> None:
    conn = message_connection()
    first = _queued_wake(conn)

    stale = stale_queued_wakes(
        conn,
        session_id="s2",
        now=NOW + ACK_GRACE - timedelta(seconds=1),
        grace_seconds=int(ACK_GRACE.total_seconds()),
    )

    assert stale == []
    assert not message_details(conn, first["message_id"])["cancelled_at"]


def test_an_ordinary_envelope_is_never_released_as_a_stale_wake() -> None:
    conn = message_connection()
    send_message(
        conn,
        message_id="11111111-1111-4111-8111-111111111111",
        actor_id=10,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=["s2"]),
        body="Stage notice for the release.",
        now=NOW,
    )

    stale = stale_queued_wakes(
        conn,
        session_id="s2",
        now=PAST_THE_WINDOW,
        grace_seconds=int(ACK_GRACE.total_seconds()),
    )

    assert stale == []

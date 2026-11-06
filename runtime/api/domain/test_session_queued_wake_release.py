"""Manual retries preserve every pending envelope whose content they do not carry."""

from datetime import timedelta

import pytest

from yoke_core.domain.session_manual_wake import request_session_wake
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_contracts.session_control.models import RecipientSelector
from runtime.api.domain.session_message_support_test_support import (
    ACK_GRACE,
    NOW,
    message_connection,
)


PAST_THE_WINDOW = NOW + ACK_GRACE + timedelta(seconds=1)


def _wake(conn, *, key, now=NOW, prompt=None):
    return request_session_wake(
        conn,
        actor_id=10,
        caller_session_id=None,
        session_id="s2",
        public_ref=None,
        prompt=prompt,
        idempotency_key=key,
        now=now,
    )


def test_unattempted_stale_wake_stops_blocking_but_keeps_its_content():
    conn = message_connection()
    first = _wake(
        conn, key="first-wake", prompt="The deployment QA action is still owed."
    )
    second = _wake(conn, key="second-wake", now=PAST_THE_WINDOW)
    assert second["message_id"] != first["message_id"]
    original = message_details(conn, first["message_id"])
    assert original["cancelled_at"] is None
    assert original["recipients"][0]["state"] == "pending"
    assert original["body"] == "The deployment QA action is still owed."


def test_queued_wake_inside_grace_still_blocks_another_native_resume():
    conn = message_connection()
    first = _wake(conn, key="first-wake")
    with pytest.raises(SessionMessageError, match="wake_queued") as error:
        _wake(conn, key="second-wake", now=NOW + ACK_GRACE - timedelta(seconds=1))
    assert error.value.code == "wake_in_flight"
    assert message_details(conn, first["message_id"])["cancelled_at"] is None


def test_manual_wake_preserves_an_ordinary_pending_envelope():
    conn = message_connection()
    original = send_message(
        conn,
        actor_id=10,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=["s2"]),
        body="Stage notice for the release.",
        now=NOW,
    )
    _wake(conn, key="new-wake", now=PAST_THE_WINDOW)
    assert (
        message_details(conn, original["message_id"])["recipients"][0]["state"]
        == "pending"
    )


def test_cancelled_explicit_intent_gets_a_fresh_receipt_on_retry():
    from yoke_core.domain.session_message_receipts import cancel_message

    conn = message_connection()
    first = _wake(conn, key="same-intent")
    cancel_message(conn, message_id=first["message_id"], actor_id=10, now=NOW)
    second = _wake(conn, key="same-intent", now=PAST_THE_WINDOW)
    assert second["message_id"] != first["message_id"]
    assert second["deduplicated"] is False
    assert message_details(conn, first["message_id"])["cancelled_at"] is not None
    assert (
        _wake(conn, key="same-intent", now=PAST_THE_WINDOW)["message_id"]
        == second["message_id"]
    )

"""One more direct try after an undelivered turn, then the broker takes it."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_contracts.session_control.wake_delivery import (
    TURN_WITHOUT_INJECTION_RESULT,
)
from yoke_core.domain.session_broker_wake_fallback import (
    direct_wake_waits_for_broker,
)
from yoke_core.domain.session_message_service import send_message
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    message_connection,
    selector,
)


def _stamp(seconds: int = 0) -> str:
    return (NOW + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _attempt(conn, attempt_id: str, message_id: str, result_code: str, at: str) -> None:
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,"
        "completed_at,result_code,evidence) VALUES (?,?,?,?,?,?,?,?)",
        (
            attempt_id,
            message_id,
            NATIVE_WAKE_SESSION_ID,
            "wake_relay",
            at,
            at,
            result_code,
            json.dumps({}),
        ),
    )
    conn.commit()


def _waits(conn, message_id: str, *, at: str) -> bool:
    return direct_wake_waits_for_broker(
        conn,
        message_id=message_id,
        session_id=NATIVE_WAKE_SESSION_ID,
        now=at,
    )


def test_the_first_undelivered_turn_earns_one_more_direct_try() -> None:
    """The instruction now asks the turn to read its own message.

    Delivery no longer depends on the resumed turn happening to make some
    tool call of its own, so one turn that answered without reading is a
    turn ignoring its instruction, not a route that cannot be reached.
    """
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, TURN_WITHOUT_INJECTION_RESULT, _stamp(10))

    assert not _waits(conn, message_id, at=_stamp(20))


def test_a_second_undelivered_turn_hands_the_receipt_to_the_broker() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, TURN_WITHOUT_INJECTION_RESULT, _stamp(10))
    _attempt(conn, "a2", message_id, TURN_WITHOUT_INJECTION_RESULT, _stamp(20))

    assert _waits(conn, message_id, at=_stamp(30))


def test_every_other_direct_failure_still_hands_off_at_once() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, "failed", _stamp(10))

    assert _waits(conn, message_id, at=_stamp(20))


def test_the_hand_off_expires_with_the_broker_job() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, "failed", _stamp(10))

    assert not _waits(conn, message_id, at=_stamp(10 + 300))

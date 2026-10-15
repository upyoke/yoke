"""One more direct try after an undelivered turn, then the broker takes it."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import parse_instant
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


class _NativeCompletionConnection:
    """Return the PostgreSQL datetime shape from the existing SQLite fixture."""

    def __init__(self, conn, *, completed=None):
        self.conn = conn
        self._conn = conn
        self.completed = completed

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, sql, params=()):
        cursor = self.conn.execute(sql, params)
        if sql.startswith("SELECT attempt_kind,result_code,completed_at "):
            row = cursor.fetchone()
            if row is not None:
                clock = (
                    self.completed
                    if self.completed is not None
                    else parse_instant(row[2])
                )
                row = (row[0], row[1], clock)

            class Result:
                def fetchone(self):
                    return row

            return Result()
        return cursor


@pytest.mark.parametrize("seconds,expected", [(299, True), (300, False), (301, False)])
def test_native_failed_completion_preserves_broker_cooldown(seconds, expected):
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, "relay_lease_expired", _stamp(10))
    assert (
        _waits(_NativeCompletionConnection(conn), message_id, at=_stamp(10 + seconds))
        is expected
    )


@pytest.mark.parametrize("attempts,expected", [(1, False), (2, True)])
def test_native_undelivered_completion_preserves_retry_budget(attempts, expected):
    conn = message_connection()
    message_id = _send(conn)
    for index in range(attempts):
        _attempt(
            conn, f"a{index}", message_id, TURN_WITHOUT_INJECTION_RESULT, _stamp(index)
        )
    assert (
        _waits(_NativeCompletionConnection(conn), message_id, at=_stamp(30)) is expected
    )


def test_malformed_completion_still_refuses():
    conn = message_connection()
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, "relay_lease_expired", _stamp(10))
    with pytest.raises(ValueError, match="invalid_instant"):
        _waits(
            _NativeCompletionConnection(conn, completed="not-a-clock"),
            message_id,
            at=_stamp(30),
        )


def test_native_failed_completion_allows_actual_relay_claim_after_cooldown():
    from yoke_core.domain.session_relay_wake_claim import (
        wake_candidates,
        claim_wake_attempt,
    )
    from yoke_core.domain.session_relay_types import RelayHeartbeat
    from runtime.api.domain.test_session_relay_wake_claim import _waiting

    conn = message_connection()
    _waiting(conn)
    message_id = _send(conn)
    _attempt(conn, "a1", message_id, "relay_lease_expired", _stamp(10))
    native = _NativeCompletionConnection(conn)
    heartbeat = RelayHeartbeat(
        relay_id="machine:m4",
        actor_id=10,
        machine_id="m4",
        hostname="relay-host",
        relay_version="0.1.1",
        surface_versions={"codex-cli": "0.148.0a15"},
        project_ids=(1,),
    )
    assert wake_candidates(native, heartbeat, now=_stamp(309)) == ()
    candidates = wake_candidates(native, heartbeat, now=_stamp(310))
    assert len(candidates) == 1
    claim = claim_wake_attempt(native, candidate=candidates[0], now=_stamp(310))
    assert claim is not None
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == 1
    )

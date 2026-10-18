"""Injected-but-unacknowledged messages come back on a bounded backoff."""

from __future__ import annotations

from datetime import timedelta

import pytest

import yoke_core.domain.session_message_delivery as message_delivery
from yoke_contracts.fleet_policy import WAKE_ACK_GRACE_SECONDS
from yoke_contracts.session_control.capabilities import capabilities_for_harness
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_reminders import (
    REMINDER_MAX_INTERVAL_SECONDS,
    reminder_interval_seconds,
)
from yoke_core.domain.session_message_service import send_message
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


#: Every surface of every harness, with each event its manifest injects on.
SURFACE_EVENTS = [
    (surface, event)
    for harness in ("claude-code", "codex", "cursor")
    for surface, facts in capabilities_for_harness(harness).items()
    for event in facts["inject_events"]
]


class _Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    current = _Clock()
    monkeypatch.setattr(message_delivery, "utc_now", current)
    return current


def _lease_and_settle(conn, event: str) -> list[dict]:
    lease = lease_for_hook(conn, session_id="s1", hook_event=event, limit=10)
    if lease is None:
        return []
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )
    return lease["messages"]


def test_the_backoff_doubles_from_the_grace_and_is_capped() -> None:
    assert reminder_interval_seconds(1) == WAKE_ACK_GRACE_SECONDS
    assert reminder_interval_seconds(2) == 2 * WAKE_ACK_GRACE_SECONDS
    assert reminder_interval_seconds(3) == 4 * WAKE_ACK_GRACE_SECONDS
    assert reminder_interval_seconds(99) == REMINDER_MAX_INTERVAL_SECONDS


@pytest.mark.parametrize(("surface", "event"), SURFACE_EVENTS)
def test_an_unacked_message_is_re_presented_once_per_backoff(
    clock: _Clock, surface: str, event: str
) -> None:
    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Re-run the merge watcher.",
        now=NOW,
    )["message_id"]
    # Delivery reads only the recipient's surface; the send route is fixed.
    conn.execute(
        "UPDATE harness_sessions SET executor_surface=? WHERE session_id='s1'",
        (surface,),
    )
    conn.commit()

    first = _lease_and_settle(conn, event)
    assert [m["message_id"] for m in first] == [message_id]
    assert "shown_count" not in first[0]

    clock.now = NOW + timedelta(seconds=WAKE_ACK_GRACE_SECONDS - 1)
    assert _lease_and_settle(conn, event) == []

    clock.now = NOW + timedelta(seconds=WAKE_ACK_GRACE_SECONDS)
    reminder = _lease_and_settle(conn, event)
    assert [(m["message_id"], m["shown_count"]) for m in reminder] == [(message_id, 1)]
    assert _lease_and_settle(conn, event) == []

    second_at = clock.now
    clock.now = second_at + timedelta(seconds=2 * WAKE_ACK_GRACE_SECONDS - 1)
    assert _lease_and_settle(conn, event) == []
    clock.now = second_at + timedelta(seconds=2 * WAKE_ACK_GRACE_SECONDS)
    assert [m["shown_count"] for m in _lease_and_settle(conn, event)] == [2]

    acknowledge_message(conn, message_id=message_id, session_id="s1", now=clock.now)
    clock.now = clock.now + timedelta(seconds=REMINDER_MAX_INTERVAL_SECONDS)
    assert _lease_and_settle(conn, event) == []


def test_a_reminder_does_not_count_as_pending_backlog(clock: _Clock) -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="First.",
        now=NOW,
    )
    _lease_and_settle(conn, "PostToolUse")
    clock.now = NOW + timedelta(seconds=WAKE_ACK_GRACE_SECONDS)
    lease = lease_for_hook(conn, session_id="s1", hook_event="PostToolUse", limit=10)
    assert lease["remaining_count"] == 0
    assert [m["shown_count"] for m in lease["messages"]] == [1]

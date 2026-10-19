"""Relay workers that cannot hold a turn are woken, bounded, and escalated."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain import session_manual_wake
from yoke_core.domain import turn_end_relay_continuation as relay
from yoke_core.domain.session_message_types import SessionMessageError


CLAIM = {"item_id": 42, "status": "implementing"}


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE harness_sessions (session_id TEXT, actor_id INTEGER)")
    db.execute("INSERT INTO harness_sessions VALUES ('worker', 7)")
    return db


@pytest.fixture
def ledger(monkeypatch) -> list[dict]:
    holds: list[dict] = []
    monkeypatch.setattr(relay, "_item_ref", lambda _conn, _id: "YOK-42")
    monkeypatch.setattr(
        relay,
        "promised_work_holds",
        lambda _conn, **_kw: (None, len(holds)),
    )
    monkeypatch.setattr(
        relay,
        "record_promised_work_hold",
        lambda _conn, **kw: holds.append(kw),
    )
    return holds


@pytest.fixture
def mail(monkeypatch) -> list[dict]:
    sent: list[dict] = []
    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message",
        lambda _conn, **kw: sent.append(kw),
    )
    return sent


def _wake_with(monkeypatch, effect) -> list[dict]:
    calls: list[dict] = []

    def wake(_conn, **kw):
        calls.append(kw)
        return effect(kw)

    monkeypatch.setattr(session_manual_wake, "request_session_wake", wake)
    return calls


def test_wake_is_queued_as_the_worker_and_counted_as_a_hold(
    monkeypatch, conn, ledger, mail
) -> None:
    calls = _wake_with(monkeypatch, lambda _kw: {"message_id": "m-1"})

    reason = relay.continue_relay_worker(
        conn, session_id="worker", claim=CLAIM, at_cap=False
    )

    assert reason == relay.REASON_RELAY_WAKE_QUEUED
    assert calls[0]["actor_id"] == 7
    assert calls[0]["session_id"] == "worker"
    assert "YOK-42" in calls[0]["prompt"]
    assert "automatic continuation 1" in calls[0]["prompt"]
    assert [hold["item_id"] for hold in ledger] == [42]
    assert mail == []


def test_cap_alarms_steering_once_and_queues_no_wake(
    monkeypatch, conn, ledger, mail
) -> None:
    calls = _wake_with(monkeypatch, lambda _kw: pytest.fail("woken at the cap"))
    ledger.extend([{}, {}, {}])

    reason = relay.continue_relay_worker(
        conn, session_id="worker", claim=CLAIM, at_cap=True
    )

    assert reason == relay.REASON_CAP_REACHED
    assert calls == []
    assert len(ledger) == 3
    assert mail[0]["selector"].steering is True
    assert mail[0]["sender_session_id"] == "worker"
    assert mail[0]["idempotency_key"] == (f"{relay.ALARM_KEY_PREFIX}:worker:42:3:cap")
    assert "reinjection_cap_reached" in mail[0]["body"]
    assert "session-control session wake worker" in mail[0]["body"]


def test_refused_wake_alarms_steering_with_the_named_reason(
    monkeypatch, conn, ledger, mail
) -> None:
    def refuse(_kw):
        raise SessionMessageError(
            "manual_wake_route_unavailable", "Run `yoke relay status`."
        )

    _wake_with(monkeypatch, refuse)

    reason = relay.continue_relay_worker(
        conn, session_id="worker", claim=CLAIM, at_cap=False
    )

    assert reason == relay.REASON_RELAY_WAKE_REFUSED
    assert ledger == []
    assert "manual_wake_route_unavailable" in mail[0]["body"]
    assert "yoke relay status" in mail[0]["body"]


def test_unresolved_actor_is_a_named_refusal(monkeypatch, conn, ledger, mail) -> None:
    conn.execute("DELETE FROM harness_sessions")
    _wake_with(monkeypatch, lambda _kw: pytest.fail("woken without an actor"))

    reason = relay.continue_relay_worker(
        conn, session_id="worker", claim=CLAIM, at_cap=False
    )

    assert reason == relay.REASON_RELAY_WAKE_REFUSED
    assert mail == []


def test_refused_alarm_never_escapes_the_stop(monkeypatch, conn, ledger) -> None:
    def no_seat(_conn, **_kw):
        raise SessionMessageError("steering_seat_absent", "no seat")

    monkeypatch.setattr(
        "yoke_core.domain.session_message_service.send_message", no_seat
    )

    assert (
        relay.continue_relay_worker(conn, session_id="worker", claim=CLAIM, at_cap=True)
        == relay.REASON_CAP_REACHED
    )


def test_notice_names_the_landed_close_out_recovery() -> None:
    notice = relay.continuation_notice(
        "YOK-42", {**CLAIM, "merged_at": "2026-10-19T08:00:00Z"}, 2
    )

    assert "yoke merge item" in notice
    assert "automatic continuation 2" in notice


def test_queued_wake_takes_the_explicit_stopped_route(monkeypatch) -> None:
    """Against the real message store: the worker's own actor wakes it."""
    from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
    from yoke_core.domain.session_message_store import message_details
    from yoke_core.domain.session_message_wake import wake_eligible_recipients
    from runtime.api.domain.test_session_message_support import (
        NOW,
        message_connection,
    )

    db = message_connection()
    monkeypatch.setattr(session_manual_wake, "utc_now", lambda: NOW)
    monkeypatch.setattr(relay, "utc_now", lambda: NOW)

    reason = relay.continue_relay_worker(
        db,
        session_id="s2",
        claim={"item_id": 101, "status": "implementing"},
        at_cap=False,
    )

    assert reason == relay.REASON_RELAY_WAKE_QUEUED
    candidate = wake_eligible_recipients(db, now=NOW)[0]
    assert candidate["session_id"] == "s2"
    details = message_details(db, candidate["message_id"])
    assert "automatic continuation 1" in details["body"]
    snapshot = details["recipients"][0]["routing_snapshot"]
    assert snapshot[EXPLICIT_WAKE_ROUTING_FLAG] is True

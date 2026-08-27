"""Escalation coverage for a pending envelope whose hook route stopped."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_starvation import STARVED_HOOK_ROUTE
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_versions import wake_operation
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


#: ``fleet.wake_ack_grace_seconds`` — the window the escalation reuses.
GRACE = timedelta(seconds=300)
STARVED = NOW + GRACE + timedelta(seconds=1)


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _stamp(conn, *, when, tool_call: str = NOW_TEXT) -> None:
    """Keep the recipient's heartbeat fresh while its turn stops ticking.

    This is the observed shape: liveness reads ``active`` off the heartbeat
    the whole time, so no idle path ever fires, while the hook route that
    would have delivered the envelope has already stopped running.
    """
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id='s1'",
        (when.strftime("%Y-%m-%dT%H:%M:%SZ"), tool_call),
    )
    conn.commit()


def _refuse_hook_delivery(conn, message_id: str) -> None:
    """Record the injection a hook would have made, without waking."""
    conn.execute(
        "UPDATE session_message_recipients SET injection_count=1,"
        "last_injected_at=? WHERE message_id=?",
        (NOW_TEXT, message_id),
    )
    conn.commit()


def test_a_served_hook_route_is_left_alone() -> None:
    conn = message_connection()
    _send(conn)
    _stamp(
        conn,
        when=STARVED,
        tool_call=(NOW + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # A tool call after the envelope arrived means a hook ran and declined to
    # attach it. That is a delivery defect, not an absent route.
    assert wake_eligible_recipients(conn, now=STARVED) == []


def test_a_starved_envelope_escalates_to_the_stopped_session_route() -> None:
    conn = message_connection()
    _send(conn)
    _stamp(conn, when=STARVED)
    eligible = wake_eligible_recipients(conn, now=STARVED)
    assert len(eligible) == 1
    candidate = eligible[0]
    assert candidate["liveness"] == "active"
    assert candidate["wake_escalation"] == STARVED_HOOK_ROUTE
    assert (
        wake_operation(candidate["wake_mode"], candidate["liveness"])
        == "message_stopped"
    )


def test_the_grace_window_bounds_the_escalation() -> None:
    conn = message_connection()
    _send(conn)
    early = NOW + GRACE - timedelta(seconds=1)
    _stamp(conn, when=early)
    assert wake_eligible_recipients(conn, now=early) == []
    _stamp(conn, when=STARVED)
    assert len(wake_eligible_recipients(conn, now=STARVED)) == 1


def test_an_injected_envelope_is_not_starved() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _refuse_hook_delivery(conn, message_id)
    _stamp(conn, when=STARVED)
    assert wake_eligible_recipients(conn, now=STARVED) == []


def test_the_escalated_attempt_records_why_it_fired() -> None:
    conn = message_connection()
    _send(conn)
    _stamp(conn, when=STARVED)
    candidate = wake_eligible_recipients(conn, now=STARVED)[0]
    claim = claim_wake_attempt(
        conn, candidate=candidate, now=STARVED.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    assert claim is not None
    evidence = json.loads(
        conn.execute(
            "SELECT evidence FROM session_message_attempts WHERE attempt_id=?",
            (claim.attempt_id,),
        ).fetchone()[0]
    )
    assert evidence["wake_escalation"] == STARVED_HOOK_ROUTE


def test_one_escalated_wake_per_recipient_per_window() -> None:
    conn = message_connection()
    _send(conn)
    _stamp(conn, when=STARVED)
    candidate = wake_eligible_recipients(conn, now=STARVED)[0]
    stamp = STARVED.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert claim_wake_attempt(conn, candidate=candidate, now=stamp) is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code='failed' "
        "WHERE completed_at IS NULL",
        (stamp,),
    )
    conn.commit()
    # The resume spawns a real process; the recorded wake holds the recipient
    # for the rest of the window even once its attempt has closed.
    later = STARVED + timedelta(seconds=1)
    _stamp(conn, when=later)
    assert wake_eligible_recipients(conn, now=later) == []
    next_window = STARVED + GRACE + timedelta(seconds=1)
    _stamp(conn, when=next_window)
    assert len(wake_eligible_recipients(conn, now=next_window)) == 1


def test_the_broker_re_read_keeps_the_escalation_it_already_stamped() -> None:
    conn = message_connection()
    _send(conn)
    _stamp(conn, when=STARVED)
    candidate = wake_eligible_recipients(conn, now=STARVED)[0]
    stamp = STARVED.strftime("%Y-%m-%dT%H:%M:%SZ")
    claim = claim_wake_attempt(conn, candidate=candidate, now=stamp)
    assert claim is not None
    # The broker reserves first and re-derives the candidate afterwards, so
    # its own stamped wake must not read as a competing one.
    adopted = wake_eligible_recipients(
        conn,
        now=STARVED,
        bypass_waiting_retry_cooldown=True,
        ignore_attempt_id=claim.attempt_id,
    )
    assert [row["wake_escalation"] for row in adopted] == [STARVED_HOOK_ROUTE]

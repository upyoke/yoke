"""Escalation coverage for a pending envelope whose hook route stopped."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_starvation import (
    PARKED_WITHOUT_IDLE_WAKE,
    STARVED_HOOK_ROUTE,
    parked_without_idle_wake,
)
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_versions import wake_operation
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
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
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _stamp(
    conn,
    *,
    when,
    tool_call: str = NOW_TEXT,
    session_id: str = NATIVE_WAKE_SESSION_ID,
) -> None:
    """Keep the recipient's heartbeat fresh while its turn stops ticking.

    This is the observed shape: liveness reads ``active`` off the heartbeat
    the whole time, so no idle path ever fires, while the hook route that
    would have delivered the envelope has already stopped running.
    """
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id=?",
        (when.strftime("%Y-%m-%dT%H:%M:%SZ"), tool_call, session_id),
    )
    conn.commit()


def _park(conn, session_id: str = NATIVE_WAKE_SESSION_ID) -> None:
    """Stamp the posture the session declared about itself.

    The shared fixture composes ``harness_sessions`` by hand, so the posture
    column arrives with the test that needs it, as it does in its siblings.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(harness_sessions)")}
    if "mode" not in columns:
        conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute(
        "UPDATE harness_sessions SET mode='parked' WHERE session_id=?",
        (session_id,),
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


def test_a_parked_recipient_without_idle_wake_needs_no_grace_window() -> None:
    conn = message_connection()
    _send(conn)
    _park(conn)
    # A codex worker declares idle wake none, so nothing is coming that would
    # run a hook: waiting out the window only postpones the one way in.
    early = NOW + timedelta(seconds=1)
    _stamp(conn, when=early)
    eligible = wake_eligible_recipients(conn, now=early)
    assert len(eligible) == 1
    candidate = eligible[0]
    assert candidate["liveness"] == "active"
    assert candidate["wake_escalation"] == PARKED_WITHOUT_IDLE_WAKE
    assert (
        wake_operation(candidate["wake_mode"], candidate["liveness"])
        == "message_stopped"
    )


def test_a_parked_recipient_that_can_wake_itself_keeps_the_grace_window() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s2"]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )
    _park(conn, "s2")
    early = NOW + timedelta(seconds=1)
    _stamp(conn, when=early, session_id="s2")
    # claude-code declares an idle wake, so a parked session there can still
    # be resumed by its own machinery until its route proves starved.
    assert wake_eligible_recipients(conn, now=early) == []
    _stamp(conn, when=STARVED, session_id="s2")
    eligible = wake_eligible_recipients(conn, now=STARVED)
    assert [row["wake_escalation"] for row in eligible] == [STARVED_HOOK_ROUTE]


def test_the_parked_escalation_is_recorded_on_the_receipt_and_attempt() -> None:
    conn = message_connection()
    message_id = _send(conn)
    _park(conn)
    early = NOW + timedelta(seconds=1)
    _stamp(conn, when=early)
    candidate = wake_eligible_recipients(conn, now=early)[0]
    claim = claim_wake_attempt(
        conn, candidate=candidate, now=early.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    assert claim is not None
    receipt = conn.execute(
        "SELECT wake_escalation,wake_attempt_count FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert receipt["wake_escalation"] == PARKED_WITHOUT_IDLE_WAKE
    assert receipt["wake_attempt_count"] == 1
    evidence = json.loads(
        conn.execute(
            "SELECT evidence FROM session_message_attempts WHERE attempt_id=?",
            (claim.attempt_id,),
        ).fetchone()[0]
    )
    assert evidence["wake_escalation"] == PARKED_WITHOUT_IDLE_WAKE


def test_one_parked_escalation_per_recipient_per_window() -> None:
    conn = message_connection()
    _send(conn)
    _park(conn)
    early = NOW + timedelta(seconds=1)
    _stamp(conn, when=early)
    candidate = wake_eligible_recipients(conn, now=early)[0]
    stamp = early.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert claim_wake_attempt(conn, candidate=candidate, now=stamp) is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code='failed' "
        "WHERE completed_at IS NULL",
        (stamp,),
    )
    conn.commit()
    # The resume spawns a real process, so the recorded wake holds the parked
    # recipient for the rest of the window exactly as a starved one.
    later = early + timedelta(seconds=1)
    _stamp(conn, when=later)
    assert wake_eligible_recipients(conn, now=later) == []
    next_window = early + GRACE + timedelta(seconds=1)
    _stamp(conn, when=next_window)
    assert len(wake_eligible_recipients(conn, now=next_window)) == 1


def _parked_row(surface: str, version: str) -> dict:
    return {
        "state": "pending",
        "injection_count": 0,
        "message_created_at": NOW_TEXT,
        "last_tool_call_at": NOW_TEXT,
        "mode": "parked",
        "executor": "codex",
        "executor_surface": surface,
        "executor_version": version,
    }


def test_only_a_surface_with_its_own_stopped_route_is_escalated() -> None:
    later = NOW + timedelta(seconds=1)
    headless = _parked_row("codex-cli", "0.148.0a15")
    desktop = _parked_row("codex-desktop", "26.814.41407")
    assert parked_without_idle_wake(headless, grace_seconds=300, now=later)
    # A desktop conversation is a person's open window. Its capability
    # declares no stopped route of its own, and resuming it through the
    # same-machine CLI peer would fork the transcript they are reading.
    assert not parked_without_idle_wake(desktop, grace_seconds=300, now=later)


def test_a_parked_desktop_recipient_is_never_wake_eligible() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )
    _park(conn, "s1")
    for when in (NOW + timedelta(seconds=1), STARVED):
        _stamp(conn, when=when, session_id="s1")
        assert wake_eligible_recipients(conn, now=when) == []

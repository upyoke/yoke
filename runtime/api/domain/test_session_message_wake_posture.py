"""Scheduler-authority and cooldown coverage for posture-aware wakes."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.session_turn_posture import stamp_turn_posture
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


def _send(conn) -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _stop(conn, session_id: str = "s1") -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, session_id),
    )
    conn.commit()


def test_wake_candidates_require_elapsed_deadline_and_inactive_liveness() -> None:
    deadline_conn = message_connection()
    _send(deadline_conn)
    _stop(deadline_conn)
    assert wake_eligible_recipients(deadline_conn, now=NOW + timedelta(minutes=9)) == []
    assert (
        len(wake_eligible_recipients(deadline_conn, now=NOW + timedelta(minutes=11)))
        == 1
    )

    active_conn = message_connection()
    _send(active_conn)
    assert wake_eligible_recipients(active_conn, now=NOW + timedelta(minutes=11)) == []


def test_unsupported_route_stays_terminal_until_routing_facts_change() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor_surface='cursor-desktop',"
        "executor_version='3.17.8',ended_at=? WHERE session_id='s1'",
        (NOW_TEXT,),
    )
    conn.commit()
    message_id = _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    conn.execute(
        "UPDATE session_message_recipients SET executor_surface='codex-desktop',"
        "executor_version='26.814.41407' WHERE message_id=?",
        (message_id,),
    )
    conn.commit()
    assert len(wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))) == 1


def test_candidates_carry_scheduler_authority_separately_from_liveness() -> None:
    idle_conn = message_connection()
    _send(idle_conn)
    _stop(idle_conn)

    idle = wake_eligible_recipients(idle_conn, now=NOW + timedelta(minutes=11))[0]

    assert idle["wake_mode"] == WakeMode.IDLE_TIMEOUT
    assert idle["turn_posture"] == "unknown"
    assert idle["liveness"] == "ended"

    waiting_conn = message_connection()
    stamp_turn_posture(
        waiting_conn,
        session_id="s1",
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    waiting_conn.commit()
    _send(waiting_conn)
    _stop(waiting_conn)

    waiting = wake_eligible_recipients(waiting_conn, now=NOW + timedelta(minutes=11))[0]

    assert waiting["wake_mode"] == WakeMode.WAITING
    assert waiting["turn_posture"] == "waiting"
    assert waiting["liveness"] == "ended"


def test_waiting_retry_uses_the_project_idle_policy_as_cooldown() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE organizations SET settings=? WHERE id=1",
        (json.dumps({"fleet": {"wake_after_idle_minutes": 3}}),),
    )
    stamp_turn_posture(
        conn,
        session_id="s1",
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.commit()
    _send(conn)
    _stop(conn)
    first = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))[0]
    claim = claim_wake_attempt(conn, candidate=first, now="2026-08-22T16:11:00Z")
    assert claim is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code='failed' "
        "WHERE attempt_id=?",
        ("2026-08-22T16:11:01Z", claim.attempt_id),
    )
    conn.commit()

    assert (
        wake_eligible_recipients(conn, now=NOW + timedelta(minutes=13, seconds=59))
        == []
    )
    retry = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=14, seconds=1))
    assert [row["wake_mode"] for row in retry] == [WakeMode.WAITING]


def test_waiting_posture_never_falls_through_an_expired_injection_lease() -> None:
    conn = message_connection()
    stamp_turn_posture(
        conn,
        session_id="s1",
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.commit()
    _send(conn)
    _stop(conn)
    conn.execute(
        "UPDATE session_message_recipients SET injection_lease_id='old-hook',"
        "injection_lease_expires_at=?",
        ("2026-08-22T16:00:01Z",),
    )
    conn.commit()

    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

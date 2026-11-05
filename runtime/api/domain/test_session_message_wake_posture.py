"""Scheduler-authority and cooldown coverage for posture-aware wakes."""

from __future__ import annotations

from yoke_contracts.fleet_policy import WAKE_AFTER_IDLE_SECONDS

from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_types import WakeMode
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.session_turn_posture import stamp_turn_posture
from runtime.api.domain.session_message_support_test_support import (
    NATIVE_WAKE_SESSION_ID,
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
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Never pass this body to a native wake.",
        now=NOW,
    )["message_id"]


def _stop(conn, session_id: str = NATIVE_WAKE_SESSION_ID) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, session_id),
    )
    conn.commit()


def test_an_ended_session_is_not_woken_by_age_alone() -> None:
    conn = message_connection()
    _send(conn)
    _stop(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=59)) == []
    assert wake_eligible_recipients(conn, now=NOW + timedelta(days=30)) == []


def test_long_idle_session_with_a_fresh_message_wakes_on_the_next_sweep() -> None:
    conn = message_connection()
    _send(conn)
    assert len(wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))) == 1


def test_actively_working_session_with_a_pending_message_is_never_woken() -> None:
    conn = message_connection()
    _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=90)) == []
    # Working means the turn keeps calling tools, not merely that the
    # heartbeat is fresh. Past the acknowledgement grace window those two
    # stop meaning the same thing: a session whose hooks have not run since
    # the envelope arrived is starved rather than served, and is escalated.
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id=?",
        (
            "2026-08-22T16:10:00Z",
            "2026-08-22T16:10:00Z",
            NATIVE_WAKE_SESSION_ID,
        ),
    )
    conn.commit()
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []


def test_unsupported_route_stays_terminal_until_routing_facts_change() -> None:
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor_surface='cursor-desktop',"
        "executor_version='3.17.8' WHERE session_id=?",
        (NATIVE_WAKE_SESSION_ID,),
    )
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.commit()
    message_id = _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    conn.execute(
        "UPDATE session_message_recipients SET executor_surface='codex-cli',"
        "executor_version='0.148.0a15' WHERE message_id=?",
        (message_id,),
    )
    conn.commit()
    assert len(wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))) == 1


def test_candidates_carry_scheduler_authority_separately_from_liveness() -> None:
    waiting_conn = message_connection()
    stamp_turn_posture(
        waiting_conn,
        session_id=NATIVE_WAKE_SESSION_ID,
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


def test_waiting_retry_obeys_the_fixed_idle_cooldown() -> None:
    conn = message_connection()
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
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
        wake_eligible_recipients(
            conn, now=NOW + timedelta(minutes=11, seconds=WAKE_AFTER_IDLE_SECONDS - 1)
        )
        == []
    )
    retry = wake_eligible_recipients(
        conn, now=NOW + timedelta(minutes=11, seconds=WAKE_AFTER_IDLE_SECONDS + 1)
    )
    assert [row["wake_mode"] for row in retry] == [WakeMode.WAITING]


def test_waiting_posture_never_falls_through_an_expired_injection_lease() -> None:
    conn = message_connection()
    stamp_turn_posture(
        conn,
        session_id=NATIVE_WAKE_SESSION_ID,
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


def _injected(conn, injected_at: str, session_id: str = NATIVE_WAKE_SESSION_ID) -> None:
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',last_injected_at=? "
        "WHERE session_id=?",
        (injected_at, session_id),
    )
    conn.commit()


def test_an_injected_message_never_reenters_the_wake_queue() -> None:
    conn = message_connection()
    _send(conn)
    _stop(conn)
    _injected(conn, NOW_TEXT)

    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=299)) == []
    assert wake_eligible_recipients(conn, now=NOW + timedelta(days=30)) == []


def test_stale_running_codex_resumes_and_delivers_the_original_receipt(monkeypatch):
    from yoke_core.domain.session_message_delivery import lease_for_hook
    from yoke_core.domain.session_message_lease_complete import complete_hook_lease
    from yoke_core.domain.session_relay import claim_relay_job
    from yoke_harness.session_relay_runtime import wake_operation as relay_operation
    from runtime.api.domain.session_message_machine_wake_route_test_support import (
        WAKE_TIME,
        _heartbeat,
        _register_relay,
        _send,
        _snapshot_route,
        _surface_connection,
    )

    versions = {"codex-cli": "0.148.0-alpha.15"}
    conn = _surface_connection(
        executor="codex",
        surface="codex-cli",
        version=versions["codex-cli"],
        ended=False,
    )
    _register_relay(conn, versions)
    message_id = _send(conn)
    routing = _snapshot_route(conn, message_id)
    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))[0]
    assert candidate["turn_posture"] == "running"
    assert candidate["liveness"] == "stale"
    assert candidate["wake_mode"] == "waiting"
    outcome = claim_relay_job(
        conn,
        _heartbeat(versions),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )
    assert len(outcome.jobs) == 1
    job = outcome.jobs[0]
    assert job.message_id == message_id
    assert job.target_session_id == "s2"
    assert relay_operation(job.wake_mode, job.target_liveness) == "message_stopped"
    # The resumed session's hook delivers the original envelope, once.
    monkeypatch.setattr(
        "yoke_core.domain.session_message_delivery.utc_now", lambda: NOW
    )
    lease = lease_for_hook(conn, session_id="s2", hook_event="SessionStart", limit=10)
    assert lease["messages"][0]["message_id"] == message_id
    assert (
        complete_hook_lease(
            conn,
            lease_id=lease["lease_id"],
            injected=True,
            result="injected",
        )
        == 1
    )
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=12)) == []
    assert (
        lease_for_hook(conn, session_id="s2", hook_event="PostToolUse", limit=10)
        is None
    )


def test_idle_route_selection_uses_each_surface_capability():
    from yoke_contracts.session_control.capabilities import SESSION_SURFACE_CAPABILITIES
    from yoke_core.domain.session_relay_versions import wake_operation

    for surface, capability in SESSION_SURFACE_CAPABILITIES.items():
        expected = (
            "message_stopped" if capability.message_idle == "none" else "message_idle"
        )
        assert wake_operation("idle_timeout", "stale", surface) == expected
        assert wake_operation("idle_timeout", "active", surface) == "message_active"
        assert wake_operation("waiting", "active", surface) == "message_stopped"
        assert wake_operation("idle_timeout", "ended", surface) == "message_stopped"
    assert wake_operation("invalid", "stale", "codex-cli") is None
    assert wake_operation("idle_timeout", "stale", "unknown") == "message_idle"

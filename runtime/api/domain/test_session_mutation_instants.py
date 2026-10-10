"""Session mutation clocks stay native through focus, wake, claims and termination."""

from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.domain.test_chain_checkpoint_instants import MOMENT, ZONES, _session
from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    acquire_steering,
    seed_standard_steering_world,
)
from yoke_contracts.timestamps import format_instant, temporal_wire
from yoke_core.domain import session_termination as termination
from yoke_core.domain import sessions_render_attribution as focus
from yoke_core.domain import sessions_render_end as ending
from yoke_core.domain import sessions_render_end_if_empty as idle
from yoke_core.domain import steering_claims as steering


@pytest.mark.parametrize("zone", ZONES)
def test_focus_rotation_preserves_native_microseconds_and_nulls(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    session = _session(test_db)
    monkeypatch.setattr(focus, "utc_now", lambda: MOMENT)
    focus.set_current_item(test_db, session, "1")
    later = MOMENT + timedelta(microseconds=1)
    monkeypatch.setattr(focus, "utc_now", lambda: later)
    focus.set_current_item(test_db, session, "2")
    facts = focus.get_session_attribution(test_db, session)
    assert facts["current_item_set_at"] == later
    assert facts["recent_item_recorded_at"] == MOMENT
    assert temporal_wire(facts)["current_item_set_at"] == format_instant(later)
    focus.record_recent_item(test_db, session, "3")
    assert (
        focus.get_session_attribution(test_db, session)["recent_item_recorded_at"]
        == later
    )
    focus.release_current_item_focus(test_db, session)
    facts = focus.get_session_attribution(test_db, session)
    assert facts["current_item_id"] is None and facts["current_item_set_at"] is None
    assert facts["recent_item_recorded_at"] == later


def _message(conn, session, *, expires_at):
    message = str(uuid4())
    actor = conn.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id=%s", (session,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO session_messages (message_id,sender_actor_id,body,body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES (%s,%s,'wake','opaque','{}',%s,%s)",
        (message, actor, MOMENT, expires_at),
    )
    conn.execute(
        "INSERT INTO session_message_recipients (message_id,session_id,project_id,resolution_evidence,routing_snapshot,state,created_at,wake_after,last_wake_at) "
        "VALUES (%s,%s,1,'[]','{}','pending',%s,%s,%s)",
        (message, session, MOMENT, MOMENT, MOMENT),
    )
    return message


@pytest.mark.parametrize("zone", ZONES)
def test_wake_expiry_cutoff_is_native_and_idle_end_clock_is_exact(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(idle, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(idle, "settle_and_notify", lambda *_args, **_kwargs: None)
    session = _session(test_db)
    message = _message(test_db, session, expires_at=MOMENT + timedelta(microseconds=1))
    assert (
        idle.wake_deliveries_in_flight(test_db, [session])[session]["message_id"]
        == message
    )
    test_db.execute(
        "UPDATE session_messages SET expires_at=%s WHERE message_id=%s",
        (MOMENT, message),
    )
    assert idle.wake_deliveries_in_flight(test_db, [session]) == {}
    result = idle.end_session_if_empty(test_db, session)
    assert result["ended"]
    assert result["session"]["ended_at"] == MOMENT


@pytest.mark.parametrize("zone", ZONES)
def test_steering_claim_creation_has_native_clock_precision(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    seed_standard_steering_world(test_db)
    monkeypatch.setattr(steering, "utc_now", lambda: MOMENT)
    claim = acquire_steering(test_db, SESSION_ALPHA, PROJECT_ALPHA)
    assert (claim["claimed_at"], claim["last_heartbeat"]) == (MOMENT, MOMENT)
    row = test_db.execute(
        "SELECT claimed_at,pg_typeof(claimed_at)::text FROM work_claims WHERE id=%s",
        (claim["id"],),
    ).fetchone()
    assert row == (MOMENT, "timestamp with time zone")


@pytest.mark.parametrize("zone", ZONES)
def test_termination_and_reap_share_native_fact_with_message_cancellation(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    caller = _session(test_db)
    target = _session(test_db)
    test_db.execute(
        "UPDATE harness_sessions SET mode='operator' WHERE session_id=%s", (caller,)
    )
    actor = test_db.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id=%s", (caller,)
    ).fetchone()[0]
    monkeypatch.setattr(steering, "utc_now", lambda: MOMENT)
    steering.acquire(
        test_db,
        session_id=caller,
        project_id=1,
        actor_id=actor,
        reason="termination clock proof",
    )
    message = _message(test_db, target, expires_at=MOMENT + timedelta(hours=1))
    monkeypatch.setattr(termination, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(
        termination, "emit_session_terminated", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(ending, "utc_now", lambda: MOMENT)
    monkeypatch.setattr(ending, "settle_and_notify", lambda *_args, **_kwargs: None)
    result = termination.terminate_session(
        test_db,
        target_session_id=target,
        actor_id=actor,
        caller_session_id=caller,
        reason="clock proof",
    )
    assert result["session"]["terminated_at"] == MOMENT
    row = test_db.execute(
        "SELECT requested_at FROM session_termination_reaps WHERE target_session_id=%s",
        (target,),
    ).fetchone()
    assert row[0] == MOMENT
    row = test_db.execute(
        "SELECT cancelled_at FROM session_message_recipients WHERE message_id=%s",
        (message,),
    ).fetchone()
    assert row[0] == MOMENT

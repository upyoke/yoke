"""Watcher pulses preserve liveness without inventing hook tool work."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO, NOW, PROJECT_ID, compose, seed_session, seed_steering_scope, seed_tool_call,
)
from runtime.api.domain.test_steering_fleet_report_holder_read import _claim
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import watcher_activity
from yoke_core.domain.handlers import session_watcher_activity as handler
from yoke_core.domain.fleet_delta_alarms import (
    DeltaState, idle_holder_alarms, starved_envelope_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import EnvelopeRow, FleetSnapshot, session_rows
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.domain import sessions_list_rows
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.steering_fleet_report_holders import claim_holders


def _request(owner):
    return FunctionCallRequest(
        function="sessions.watcher_activity", actor=ActorContext(session_id=owner),
        target=TargetRef(kind="global"), payload={},
    )


def _snapshot(conn, session_id, now):
    raw = next(row for row in list_sessions(session_id=session_id) if row["session_id"] == session_id)
    return FleetSnapshot(now, "steerer", sessions=session_rows({"rows": [raw]}))


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
@pytest.mark.parametrize("tool_at", [None, LONG_AGO])
def test_running_watcher_pulse_preserves_clock_and_bounded_in_flight(
    test_db, monkeypatch, tmp_path, surface, tool_at,
):
    conn = seed_steering_scope(test_db)
    owner = "watcher-worker"
    seed_session(conn, owner, executor_surface=surface, last_tool_call_at=tool_at)
    _claim(conn, owner, 1)
    now = parse_instant(NOW)
    monkeypatch.setattr(sessions_list_rows, "utc_now", lambda: now)
    # A fresh session heartbeat alone must not hide the idle worker.
    assert claim_holders(conn, project_id=PROJECT_ID, now=NOW)[0].idle_seconds > 1200
    assert "ALARM idle-holder" in idle_holder_alarms(_snapshot(conn, owner, now), DeltaState())[0]
    call_at = now - timedelta(minutes=25)
    seed_tool_call(conn, owner, tool_use_id="watched", started_at=call_at,
                   command_summary="yoke watch pytest --impacted main --bounded")
    conn.execute("UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
                 (parse_instant(LONG_AGO), owner))
    conn.commit()
    monkeypatch.setattr(handler, "_connect_rw", lambda: nullcontext(conn))
    monkeypatch.setattr(handler, "utc_now", lambda: now)
    count = conn.execute(
        "SELECT tool_call_count FROM harness_sessions WHERE session_id=%s", (owner,),
    ).fetchone()["tool_call_count"]

    def dispatch(**kwargs):
        assert kwargs["function_id"] == "sessions.watcher_activity"
        result = handler.handle_watcher_activity(_request(kwargs["actor"].session_id))
        assert result.primary_success
        assert result.result_payload["activity_at"] == now
        return SimpleNamespace(success=True)

    monkeypatch.setattr(watcher_activity.structured_api, "call_dispatcher", dispatch)
    capture = tmp_path / "progress.log"
    capture.touch()
    elapsed = [0.0]
    pump = SessionLivenessPump(
        session_id=owner, clock=lambda: elapsed[0],
        refresh_activity=lambda sid: watcher_activity.refresh_watcher_activity(
            sid, progress_capture=capture,
        ),
    )
    elapsed[0] = 60.0
    assert pump.tick()
    row = conn.execute(
        "SELECT last_tool_call_at,last_heartbeat,tool_call_count FROM harness_sessions WHERE session_id=%s",
        (owner,),
    ).fetchone()
    assert row["last_tool_call_at"] == (parse_instant(tool_at) if tool_at else None)
    assert row["last_heartbeat"] == now
    assert conn.execute(
        "SELECT last_heartbeat FROM work_claims WHERE session_id=%s AND released_at IS NULL",
        (owner,),
    ).fetchone()["last_heartbeat"] == now
    report = compose(conn)
    assert [call.session_id for call in report.in_flight] == [owner]
    assert owner not in {holder.session_id for holder in report.idle}
    snapshot = _snapshot(conn, owner, now)
    assert snapshot.sessions[owner].in_flight
    assert idle_holder_alarms(snapshot, DeltaState()) == []
    assert conn.execute(
        "SELECT tool_call_count FROM harness_sessions WHERE session_id=%s", (owner,),
    ).fetchone()["tool_call_count"] == count
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM session_tool_calls WHERE session_id=%s", (owner,),
    ).fetchone()["n"] == 1
    stopped_at = now + timedelta(minutes=21)
    # Liveness can keep ticking after watcher work stops; it is not work.
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s", (stopped_at, owner),
    )
    conn.commit()
    holder = claim_holders(conn, project_id=PROJECT_ID, now=stopped_at)[0]
    assert holder.idle_seconds >= 3 * 3600
    assert holder.last_activity_at == parse_instant(LONG_AGO)
    monkeypatch.setattr(sessions_list_rows, "utc_now", lambda: stopped_at)
    report = compose(conn, now=stopped_at)
    assert report.in_flight == ()
    assert owner in {entry.session_id for entry in report.idle}
    state = DeltaState()
    assert not _snapshot(conn, owner, stopped_at).sessions[owner].in_flight
    assert "ALARM idle-holder" in idle_holder_alarms(_snapshot(conn, owner, stopped_at), state)[0]


def test_liveness_heartbeat_does_not_silence_an_idle_holder(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    seed_session(conn, "idle-worker", last_tool_call_at=LONG_AGO)
    _claim(conn, "idle-worker", 1)
    now = parse_instant(NOW)
    monkeypatch.setattr(sessions_list_rows, "utc_now", lambda: now)
    assert claim_holders(conn, project_id=PROJECT_ID, now=NOW)[0].idle_seconds == 3 * 3600
    assert "ALARM idle-holder" in idle_holder_alarms(_snapshot(conn, "idle-worker", now), DeltaState())[0]


def test_inactive_owner_refuses_without_advancing_activity(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    seed_session(conn, "ended-worker", ended_at=NOW, last_tool_call_at=LONG_AGO)
    conn.commit()
    monkeypatch.setattr(handler, "_connect_rw", lambda: nullcontext(conn))
    result = handler.handle_watcher_activity(_request("ended-worker"))
    assert not result.primary_success
    assert result.error.code == "watcher_owner_inactive"
    assert "Recovery:" in result.error.message
    row = conn.execute("SELECT last_tool_call_at FROM harness_sessions WHERE session_id='ended-worker'").fetchone()
    assert row["last_tool_call_at"] == parse_instant(LONG_AGO)


def test_rejected_pulse_teaches_recovery_in_own_capture(monkeypatch, tmp_path):
    capture = tmp_path / "progress.log"
    capture.write_text("# writer bound\n")
    monkeypatch.setattr(watcher_activity.structured_api, "call_dispatcher", lambda **_: SimpleNamespace(
        success=False, error=SimpleNamespace(message="function_version_skew: requires next-release"),
    ))
    assert not watcher_activity.refresh_watcher_activity("owner", progress_capture=capture)
    evidence = capture.read_text()
    assert "watcher_activity_unavailable" in evidence
    assert "function_version_skew" in evidence
    assert "Recovery:" in evidence


@pytest.mark.parametrize("tool_at", [None, LONG_AGO])
def test_stopped_seat_with_pulsing_watcher_still_alarms_on_pending_message(
    test_db, monkeypatch, tool_at,
):
    conn = seed_steering_scope(test_db)
    owner = "stopped-seat"
    seed_session(conn, owner, last_tool_call_at=tool_at)
    _claim(conn, owner, 1)
    now = parse_instant(NOW)
    monkeypatch.setattr(handler, "_connect_rw", lambda: nullcontext(conn))
    monkeypatch.setattr(handler, "utc_now", lambda: now)
    monkeypatch.setattr(sessions_list_rows, "utc_now", lambda: now)
    assert handler.handle_watcher_activity(_request(owner)).primary_success
    envelope = EnvelopeRow("pending-message", owner, "steerer", "pending", 0,
                           now - timedelta(minutes=20))
    snapshot = replace(_snapshot(conn, owner, now), envelopes={envelope.key: envelope})
    assert not snapshot.sessions[owner].in_flight
    assert "ALARM starved-envelope" in starved_envelope_alarms(snapshot, DeltaState())[0]
    assert "ALARM idle-holder" in idle_holder_alarms(snapshot, DeltaState())[0]

"""A running watcher heartbeat is activity; a stopped one eventually alarms."""

from datetime import timedelta

import pytest

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO, NOW, PROJECT_ID, seed_session, seed_steering_scope,
)
from runtime.api.domain.test_steering_fleet_report_holder_read import _claim
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import session_liveness_pump, sessions_lifecycle_registry
from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot, session_rows
from yoke_core.domain.session_liveness_pump import SessionLivenessPump
from yoke_core.domain.sessions_list_rows import _latest_activity
from yoke_core.domain.steering_fleet_report_holders import claim_holders


@pytest.mark.parametrize("surface", ["claude-cli", "codex-cli", "cursor-cli"])
@pytest.mark.parametrize("tool_at", [None, LONG_AGO])
def test_watcher_heartbeat_prevents_idle_then_ages_after_exit(
    test_db, monkeypatch, surface, tool_at,
):
    conn = seed_steering_scope(test_db)
    session_id = "watcher-worker"
    seed_session(conn, session_id, executor_surface=surface, last_tool_call_at=tool_at)
    _claim(conn, session_id, 1)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (LONG_AGO, session_id),
    )
    conn.commit()
    now = parse_instant(NOW)
    monkeypatch.setattr(sessions_lifecycle_registry, "utc_now", lambda: now)

    def refresh(owner):
        sessions_lifecycle_registry.heartbeat(conn, owner)
        return True

    monkeypatch.setattr(session_liveness_pump, "refresh_session_heartbeat", refresh)
    elapsed = [0.0]
    pump = SessionLivenessPump(session_id=session_id, clock=lambda: elapsed[0])
    elapsed[0] = 60.0
    assert pump.tick()
    assert claim_holders(conn, project_id=PROJECT_ID, now=NOW)[0].idle_seconds == 0
    stopped_at = now + timedelta(minutes=21)
    holder = claim_holders(conn, project_id=PROJECT_ID, now=stopped_at)[0]
    assert holder.idle_seconds == 21 * 60
    assert holder.last_activity_at == now

    raw = dict(conn.execute(
        "SELECT * FROM harness_sessions WHERE session_id=%s", (session_id,),
    ).fetchone())
    raw["activity_at"], _ = _latest_activity(raw["last_heartbeat"], raw["last_tool_call_at"])
    raw["claims"] = [{"target_kind": "item", "target": "YOK-1"}]
    rows = session_rows({"rows": [raw]})
    state = DeltaState()
    assert idle_holder_alarms(FleetSnapshot(now, "steerer", sessions=rows), state) == []
    assert "ALARM idle-holder" in idle_holder_alarms(
        FleetSnapshot(stopped_at, "steerer", sessions=rows), state,
    )[0]


def test_newer_tool_call_wins_over_stopped_watcher_heartbeat(test_db):
    conn = seed_steering_scope(test_db)
    seed_session(conn, "active-worker", last_tool_call_at=NOW)
    _claim(conn, "active-worker", 1)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (LONG_AGO, "active-worker"),
    )
    conn.commit()
    assert claim_holders(conn, project_id=PROJECT_ID, now=NOW)[0].idle_seconds == 0

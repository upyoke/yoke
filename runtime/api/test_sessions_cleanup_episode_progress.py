# ruff: noqa: F811
"""Current-episode boundaries protect fresh sessions from stale tool history."""

from __future__ import annotations

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import _register, conn  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_core.domain.sessions import clean_stale_harness_sessions, end_session
from yoke_core.hooks.remote_lifecycle import run_remote_session_lifecycle


def test_cleanup_ignores_prior_episode_tool_activity(conn):
    _register(conn, session_id="resumed-sess")
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s, tool_call_count = 1 "
        "WHERE session_id = 'resumed-sess'",
        (_ago_minutes(120),),
    )
    conn.commit()

    result = clean_stale_harness_sessions(
        conn,
        stale_threshold_minutes=10,
        progress_threshold_minutes=90,
    )

    assert result["progress_stale"] == []
    assert result["total_reclaimed"] == 0
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id = 'resumed-sess'"
    ).fetchone()
    assert row["ended_at"] is None


def test_remote_session_start_reclaims_only_the_stale_episode(conn, monkeypatch):
    def begin(session_id: str) -> None:
        result = begin_session(
            conn,
            session_id=session_id,
            executor="claude-cli",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace="/tmp",
            project_id=1,
        )
        assert result["success"] is True

    begin("resumed-owner")
    conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at = %s, tool_call_count = 1 "
        "WHERE session_id = 'resumed-owner'",
        (_ago_minutes(120),),
    )
    conn.commit()
    end_session(conn, "resumed-owner")
    begin("resumed-owner")

    begin("stale-peer")
    stale_at = _ago_minutes(120)
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat = %s, "
        "last_tool_call_at = %s, tool_call_count = 1, episode_started_at = %s "
        "WHERE session_id = 'stale-peer'",
        (stale_at, stale_at, stale_at),
    )
    conn.commit()

    emitted = []

    def capture(event_name, *, session_id, context=None, **_kwargs):
        emitted.append((event_name, session_id, context or {}))

    from yoke_core.domain import sessions_analytics

    monkeypatch.setattr(sessions_analytics, "_emit_event", capture)
    monkeypatch.setattr(sessions_analytics, "_emit_session_event", capture)

    run_remote_session_lifecycle("SessionStart", None)

    rows = conn.execute(
        "SELECT session_id, ended_at FROM harness_sessions "
        "WHERE session_id IN ('resumed-owner', 'stale-peer') ORDER BY session_id"
    ).fetchall()
    ended = {row["session_id"]: row["ended_at"] for row in rows}
    assert set(ended) == {"resumed-owner", "stale-peer"}
    assert ended["resumed-owner"] is None
    assert ended["stale-peer"] is not None

    reclaimed = [
        event for event in emitted if event[0] == "HarnessSessionStaleReclaimed"
    ]
    sweeps = [
        event for event in emitted if event[0] == "HarnessSessionStaleSweepCompleted"
    ]
    assert [(event[0], event[1]) for event in reclaimed] == [
        ("HarnessSessionStaleReclaimed", "stale-peer")
    ]
    assert [(event[1], event[2]["total_reclaimed"]) for event in sweeps] == [
        ("__sweep__", 1)
    ]

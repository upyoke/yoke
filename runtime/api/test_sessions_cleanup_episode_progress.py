# ruff: noqa: F811
"""Current-episode boundaries protect fresh sessions from stale tool history."""

from __future__ import annotations

from runtime.api.sessions_api_stale_test_helpers import _ago_minutes
from runtime.api.test_sessions import _register, conn  # noqa: F401
from yoke_core.domain.sessions import clean_stale_harness_sessions


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

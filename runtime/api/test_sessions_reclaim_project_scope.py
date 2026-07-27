"""Project-scoped stale-session cleanup safety."""

from __future__ import annotations

import pytest

from runtime.api.sessions_api_stale_test_helpers import (
    _ago_minutes,
    conn as session_conn,  # noqa: F401
)
from runtime.api.test_sessions import _register
from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions


class TestSessionsReclaimProjectScope:
    def test_preserves_stale_sessions_in_other_projects(
        self,
        session_conn,  # noqa: F811
        monkeypatch,
    ):
        conn = session_conn
        stale_at = _ago_minutes(30)
        for session_id, project_id in (
            ("visible-stale", 1),
            ("hidden-stale", 2),
        ):
            _register(conn, session_id=session_id, project_id=project_id)
            conn.execute(
                "UPDATE harness_sessions "
                "SET offered_at = %s, last_heartbeat = %s "
                "WHERE session_id = %s",
                (stale_at, stale_at, session_id),
            )
        conn.commit()

        from yoke_core.domain import sessions_cleanup as cleanup

        monkeypatch.setattr(
            cleanup,
            "auto_prune_stale_scratch",
            lambda _conn: pytest.fail("scoped reclaim ran the global janitor"),
        )
        result = clean_stale_harness_sessions(
            conn,
            stale_threshold_minutes=10,
            project_ids=[1],
        )

        assert result["total_reclaimed"] == 1
        assert result["scratch_cleanup"]["scope_limited"] is True
        states = {
            row["session_id"]: row["ended_at"]
            for row in conn.execute(
                "SELECT session_id, ended_at FROM harness_sessions "
                "WHERE session_id IN ('visible-stale', 'hidden-stale')"
            ).fetchall()
        }
        assert states["visible-stale"] is not None
        assert states["hidden-stale"] is None

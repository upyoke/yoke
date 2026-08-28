"""Session roster presentation projection tests."""

from __future__ import annotations

from yoke_core.domain.session_presentation_read import session_presentation
from yoke_core.domain.sessions_list_query import build_sessions_query


class _Conn:
    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return None


def test_roster_keeps_execution_and_observed_presentation_independent():
    result = session_presentation(
        _Conn(),
        {
            "executor": "claude-code",
            "executor_surface": "claude-cli",
            "execution_lane": "primary",
            "presentation_surface": "remote-control",
            "presentation_state": "attached",
            "presentation_mode": "bidirectional",
            "presentation_source": "claude-job-state",
            "presentation_observed_at": "2026-08-28T18:00:00Z",
        },
    )

    assert result["presentation_surface"] == "remote-control"
    assert result["presentation_state"] == "attached"
    assert result["executor_mark"]
    query = build_sessions_query("", windowed=False)
    assert "s.executor_surface" in query
    assert "s.presentation_surface" in query

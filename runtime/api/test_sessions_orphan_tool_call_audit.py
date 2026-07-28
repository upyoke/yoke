"""First-class interrupted-tool-call audit coverage."""

from runtime.api.test_sessions import _register
from runtime.api.test_sessions_orphan_tool_call_sweep import (
    _close_call,
    _insert_open_call,
    _seed_events,
)
from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED
from yoke_core.domain.sessions_orphan_tool_call_sweep import (
    sweep_orphaned_tool_calls,
)

pytest_plugins = ("runtime.api.test_sessions",)


def test_count_of_interrupted_rows_matches_expected(conn):
    _seed_events(conn)
    _register(conn, session_id="sess-Q")
    _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q1")
    _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q2")
    _insert_open_call(conn, session_id="sess-Q", tool_use_id="tu-q3")
    _close_call(conn, session_id="sess-Q", tool_use_id="tu-q2")
    sweep_orphaned_tool_calls(
        conn, session_id="sess-Q", lifecycle_reason="session_idle_auto_ended"
    )
    count = conn.execute(
        """SELECT COUNT(*) FROM events WHERE session_id = %s
             AND event_name = 'HarnessToolCallCompleted'
             AND event_outcome = %s""",
        ("sess-Q", OUTCOME_INTERRUPTED),
    ).fetchone()[0]
    assert count == 2
    interrupted = conn.execute(
        """SELECT COUNT(*) FROM session_tool_calls
           WHERE session_id = %s AND outcome = %s""",
        ("sess-Q", OUTCOME_INTERRUPTED),
    ).fetchone()[0]
    assert interrupted == 2

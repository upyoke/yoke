"""The sweep survives a completion event that is already recorded.

A tool call can reach the sweep with its ``HarnessToolCallCompleted`` event
already in the ledger — the hook wrote it before the process died, or an
earlier sweep's event committed while the row close behind it was rolled
back. The sentinel then collides with ``idx_events_tool_use_id_dedup``, and
an escaping integrity error takes the caller's whole transaction with it.
That is what a relay's liveness batch does every poll: rollback, the open
row survives, the next poll rebuilds the same collision, and no session in
the batch is ever settled.

So the duplicate has to read as "already delivered": the row still closes,
no second sentinel is written, and the transaction stays usable.
"""

from __future__ import annotations

from yoke_core.domain.events_tool_call_outcome import OUTCOME_INTERRUPTED
from yoke_core.domain.sessions_orphan_tool_call_sweep import sweep_orphaned_tool_calls
from runtime.api.sessions_orphan_sweep_test_schema import _seed_events

pytest_plugins = ("runtime.api.test_sessions",)


SESSION_ID = "sess-duplicate"
TOOL_USE_ID = "tu-already-completed"


def _reopen(conn) -> None:
    """Leave the row open while its completion event stays recorded."""
    conn.execute(
        "UPDATE session_tool_calls SET completed_at = NULL, outcome = NULL "
        "WHERE session_id = %s AND tool_use_id = %s",
        (SESSION_ID, TOOL_USE_ID),
    )
    conn.commit()


def _open_row_count(conn) -> int:
    rows = list(
        conn.execute(
            "SELECT id FROM session_tool_calls "
            "WHERE session_id = %s AND completed_at IS NULL",
            (SESSION_ID,),
        )
    )
    return len(rows)


def _sentinel_count(conn) -> int:
    rows = list(
        conn.execute(
            "SELECT event_id FROM events WHERE tool_use_id = %s "
            "AND event_name = 'HarnessToolCallCompleted'",
            (TOOL_USE_ID,),
        )
    )
    return len(rows)


def _seed_open_call(conn) -> None:
    _seed_events(conn)
    conn.execute(
        "INSERT INTO session_tool_calls (session_id, tool_use_id, tool_name, "
        "started_at) VALUES (%s, %s, %s, %s)",
        (SESSION_ID, TOOL_USE_ID, "Bash", "2026-09-18T05:00:00.000Z"),
    )
    conn.commit()


def test_already_recorded_completion_event_still_closes_the_row(conn):
    _seed_open_call(conn)
    first = sweep_orphaned_tool_calls(
        conn, session_id=SESSION_ID, lifecycle_reason="native_process_verified_dead"
    )
    assert len(first["sentinel_event_ids"]) == 1
    _reopen(conn)

    repeat = sweep_orphaned_tool_calls(
        conn, session_id=SESSION_ID, lifecycle_reason="native_process_verified_dead"
    )

    # The operational half happened; the telemetry half was already there.
    assert repeat["matched"] == 1
    assert repeat["sentinel_event_ids"] == []
    assert _sentinel_count(conn) == 1
    assert _open_row_count(conn) == 0
    closed = conn.execute(
        "SELECT outcome FROM session_tool_calls "
        "WHERE session_id = %s AND tool_use_id = %s",
        (SESSION_ID, TOOL_USE_ID),
    ).fetchone()
    assert closed["outcome"] == OUTCOME_INTERRUPTED


def test_the_callers_transaction_survives_the_duplicate(conn):
    _seed_open_call(conn)
    sweep_orphaned_tool_calls(
        conn, session_id=SESSION_ID, lifecycle_reason="native_process_verified_dead"
    )
    _reopen(conn)

    sweep_orphaned_tool_calls(
        conn, session_id=SESSION_ID, lifecycle_reason="native_process_verified_dead"
    )
    # A poisoned transaction refuses every later statement until rollback;
    # the batch this sweep rides along with depends on that not happening.
    conn.execute(
        "INSERT INTO session_tool_calls (session_id, tool_use_id, tool_name, "
        "started_at) VALUES (%s, %s, %s, %s)",
        (SESSION_ID, "tu-after-the-duplicate", "Bash", "2026-09-18T05:01:00.000Z"),
    )
    conn.commit()

    assert _open_row_count(conn) == 1

"""Read-only inventory commands for harness_sessions.

Hosts ``list`` (active sessions) and ``stale`` (multi-signal liveness
detection) — they are queries with no side effects, kept apart from
the lifecycle/claims write paths so callers can import the inventory
side without pulling in mutators.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_core.domain.db_helpers import query_rows

from runtime.harness.harness_sessions_focus import _format_row


def cmd_list(conn) -> str:
    rows = query_rows(
        conn,
        "SELECT session_id, executor, provider, model, execution_lane, "
        "mode, offered_at, last_heartbeat "
        "FROM harness_sessions WHERE ended_at IS NULL "
        "ORDER BY offered_at DESC",
    )
    return "\n".join(_format_row(row) for row in rows)


def cmd_stale(conn, threshold_minutes: int = 60) -> str:
    """Detect stale sessions using multiple liveness signals.

    A session is stale only when ALL of the following are true:
    - heartbeat exceeds *threshold_minutes*
    - no active (unreleased) work claims
    - no tool-call activity (``last_tool_call_at``) within the window
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = query_rows(
        conn,
        "SELECT hs.session_id, hs.executor, hs.mode, hs.last_heartbeat "
        "FROM harness_sessions hs "
        "WHERE hs.ended_at IS NULL "
        "AND hs.last_heartbeat < %s "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM work_claims wc "
        "  WHERE wc.session_id = hs.session_id AND wc.released_at IS NULL"
        ") "
        "AND (hs.last_tool_call_at IS NULL OR hs.last_tool_call_at < %s) "
        "ORDER BY hs.last_heartbeat ASC",
        (cutoff, cutoff),
    )
    return "\n".join(_format_row(row) for row in rows)

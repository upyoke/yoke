"""Batch session, claim and open-call facts with a fixed number of reads.

The shared newest-activity helper selects the same stamps as single-session
reads; session_state.session_in_flight owns the live-call decision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Sequence, Set

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns
from .session_reclaim_activity import (
    newest_activity_stamp as _newest,
)
from .session_reclaim_progress import live_activity_stamp
from .session_state import session_in_flight


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _columns(conn: Any, table: str) -> Set[str]:
    try:
        return set(_schema_get_columns(conn, table))
    except db_backend.operational_error_types():
        return set()


def _rows(conn: Any, sql: str, params: Sequence[Any]) -> List[Any]:
    try:
        return list(conn.execute(sql, tuple(params)).fetchall())
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return []


def _value(row: Any, name: str, index: int) -> Any:
    try:
        return row[name]
    except (TypeError, IndexError, KeyError):
        try:
            return row[index]
        except (TypeError, IndexError, KeyError):
            return None


def latest_activity_by_session(
    conn: Any,
    session_ids: Iterable[str],
) -> Dict[str, datetime | None]:
    """Map each session id to its canonical "is this session alive?" stamp.

    Sessions with no activity signal at all map to ``None``, matching
    :func:`session_reclaim_activity.latest_activity` for the same session.
    """
    ids = [str(value) for value in dict.fromkeys(session_ids) if value]
    if not ids:
        return {}

    marker = _p(conn)
    placeholders = ", ".join(marker for _ in ids)
    activity: Dict[str, datetime | None] = {session_id: None for session_id in ids}

    session_facts: Dict[str, dict] = {}
    session_columns = _columns(conn, "harness_sessions")
    if session_columns:
        selected = [
            name
            for name in (
                "executor", "last_heartbeat", "last_tool_call_at", "ended_at",
                "terminated_at", "mode", "turn_posture", "turn_posture_at",
                "quiet_reason", "native_process_gone_at", "native_process_gone_evidence",
            )
            if name in session_columns
        ]
        if selected:
            sql = (
                f"SELECT session_id, {', '.join(selected)} FROM harness_sessions "
                f"WHERE session_id IN ({placeholders})"
            )
            for row in _rows(conn, sql, ids):
                session_id = str(_value(row, "session_id", 0))
                values = {
                    name: _value(row, name, index + 1)
                    for index, name in enumerate(selected)
                }
                session_facts[session_id] = values
                stamps = [values.get("last_heartbeat"), values.get("last_tool_call_at")]
                activity[session_id] = _newest(activity.get(session_id), *stamps)

    claim_columns = _columns(conn, "work_claims")
    if claim_columns:
        aggregates = ["MAX(claimed_at) AS claimed_at"]
        if "last_heartbeat" in claim_columns:
            aggregates.insert(0, "MAX(last_heartbeat) AS last_heartbeat")
        sql = (
            f"SELECT session_id, {', '.join(aggregates)} FROM work_claims "
            f"WHERE released_at IS NULL AND session_id IN ({placeholders}) "
            "GROUP BY session_id"
        )
        for row in _rows(conn, sql, ids):
            session_id = str(_value(row, "session_id", 0))
            stamps = [
                _value(row, "last_heartbeat", 1)
                if "last_heartbeat" in claim_columns
                else None,
                _value(
                    row, "claimed_at", 2 if "last_heartbeat" in claim_columns else 1
                ),
            ]
            activity[session_id] = _newest(activity.get(session_id), *stamps)

    _mark_in_flight_live(conn, ids, activity, session_facts, placeholders)
    return activity


def _mark_in_flight_live(
    conn: Any,
    ids: List[str],
    activity: Dict[str, datetime | None],
    session_facts: Dict[str, dict],
    placeholders: str,
) -> None:
    """Project open calls through the same session rule as single reads."""
    live_stamp = live_activity_stamp()
    tool_columns = _columns(conn, "session_tool_calls")
    if "completed_at" not in tool_columns or "session_id" not in tool_columns:
        return
    sql = (
        "SELECT session_id, MAX(started_at) AS started_at FROM session_tool_calls "
        f"WHERE completed_at IS NULL AND session_id IN ({placeholders}) "
        "GROUP BY session_id"
    )
    for row in _rows(conn, sql, ids):
        session_id = str(_value(row, "session_id", 0))
        facts = {
            **session_facts.get(session_id, {}),
            "open_tool_call_at": _value(row, "started_at", 1),
        }
        if session_in_flight(facts, now=live_stamp):
            activity[session_id] = live_stamp


__all__ = ["latest_activity_by_session"]

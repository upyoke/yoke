"""Reading the reclaim activity signal for many sessions in one pass.

:func:`yoke_core.domain.session_reclaim_activity.read_activity_signals` answers
"is this session alive?" for one session and costs two reads plus two schema
probes. Callers that ask the same question about every live claim — the
scheduler's claim-state pass is the hot one — ask it here instead: the schema
probe happens once and the two reads are grouped, so the cost is four
statements regardless of how many sessions are in play.

The signal itself is defined once, in the single-session module: the newest of
the session's heartbeat and tool-call stamps and its live claims' heartbeat and
claim stamps. This module reproduces that selection over a set, and the shared
:func:`_newest` helper keeps the two paths from drifting apart.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from . import db_backend
from .schema_common import _get_columns as _schema_get_columns
from .session_reclaim_activity import (
    in_flight_activity_is_hard_stale,
    newest_activity_stamp as _newest,
    resolve_effective_ttl,
)
from .session_reclaim_progress import live_activity_stamp, open_tool_call_is_live


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
) -> Dict[str, Optional[str]]:
    """Map each session id to its canonical "is this session alive?" stamp.

    Sessions with no activity signal at all map to ``None``, matching
    :func:`session_reclaim_activity.latest_activity` for the same session.
    """
    ids = [str(value) for value in dict.fromkeys(session_ids) if value]
    if not ids:
        return {}

    marker = _p(conn)
    placeholders = ", ".join(marker for _ in ids)
    activity: Dict[str, Optional[str]] = {session_id: None for session_id in ids}
    executors: Dict[str, Optional[str]] = {session_id: None for session_id in ids}

    session_columns = _columns(conn, "harness_sessions")
    if session_columns:
        selected = [
            name
            for name in ("executor", "last_heartbeat", "last_tool_call_at")
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
                executors[session_id] = values.get("executor")
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

    _mark_in_flight_live(conn, ids, activity, executors, marker, placeholders)
    return activity


def _mark_in_flight_live(
    conn: Any,
    ids: List[str],
    activity: Dict[str, Optional[str]],
    executors: Dict[str, Optional[str]],
    marker: str,
    placeholders: str,
) -> None:
    """Treat a running turn or a live open tool call as present activity.

    An open ``session_tool_calls`` row only counts while it is still the
    session's newest recorded activity; the same grounding the single-session
    classifier applies, so a harness that never closes its rows cannot make a
    session permanently unreclaimable here either.
    """
    live_stamp = live_activity_stamp()

    def mark_live(row: Any) -> None:
        session_id = str(_value(row, "session_id", 0))
        if session_id not in activity or in_flight_activity_is_hard_stale(
            activity[session_id],
            effective_ttl_minutes=resolve_effective_ttl(executors.get(session_id)),
        ):
            return
        activity[session_id] = live_stamp

    session_columns = _columns(conn, "harness_sessions")
    if "turn_posture" in session_columns:
        sql = (
            f"SELECT session_id FROM harness_sessions "
            f"WHERE session_id IN ({placeholders}) AND turn_posture = {marker}"
        )
        for row in _rows(conn, sql, (*ids, "running")):
            mark_live(row)
    tool_columns = _columns(conn, "session_tool_calls")
    if "completed_at" in tool_columns and "session_id" in tool_columns:
        sql = (
            "SELECT session_id, MAX(started_at) AS started_at "
            f"FROM session_tool_calls "
            f"WHERE completed_at IS NULL AND session_id IN ({placeholders}) "
            "GROUP BY session_id"
        )
        for row in _rows(conn, sql, ids):
            session_id = str(_value(row, "session_id", 0))
            if open_tool_call_is_live(
                _value(row, "started_at", 1),
                activity.get(session_id),
            ):
                mark_live(row)


__all__ = ["latest_activity_by_session"]

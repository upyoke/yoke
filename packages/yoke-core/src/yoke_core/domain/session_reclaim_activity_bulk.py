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
from .session_reclaim_activity import newest_activity_stamp as _newest


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

    session_columns = _columns(conn, "harness_sessions")
    if session_columns:
        selected = [
            name
            for name in ("last_heartbeat", "last_tool_call_at")
            if name in session_columns
        ]
        if selected:
            sql = (
                f"SELECT session_id, {', '.join(selected)} FROM harness_sessions "
                f"WHERE session_id IN ({placeholders})"
            )
            for row in _rows(conn, sql, ids):
                session_id = str(_value(row, "session_id", 0))
                stamps = [
                    _value(row, name, index + 1)
                    for index, name in enumerate(selected)
                ]
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
                _value(row, "claimed_at", 2 if "last_heartbeat" in claim_columns else 1),
            ]
            activity[session_id] = _newest(activity.get(session_id), *stamps)

    return activity


__all__ = ["latest_activity_by_session"]

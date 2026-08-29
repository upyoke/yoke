"""Session queue posture: parked waits until an explicit mode stamp leaves it."""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_queries_base import _row_to_dict

SESSION_MODE_PARKED = "parked"
SESSION_MODE_DEFAULT = "wait"
# Grounded stamps: skill ``--mode`` values, NextAction kinds, and packet posture.
SESSION_MODES = frozenset(
    (
        SESSION_MODE_DEFAULT,
        SESSION_MODE_PARKED,
        "busy",
        "charge",
        "dash",
        "escalate",
        "feed",
        "idea",
        "operator",
        "plan",
        "polish",
        "refine",
        "resume",
        "shepherd",
        "steer",
        "strategize",
    )
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_columns(conn: Any) -> set[str]:
    try:
        return set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return set()


def _parked_reason_present(conn: Any) -> bool:
    return "parked_reason" in _session_columns(conn)


def _load_session(conn: Any, session_id: str) -> Dict[str, Any]:
    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    return _row_to_dict(row)


def session_is_parked(mode: object) -> bool:
    """True when *mode* is the canonical parked posture."""
    return str(mode or "") == SESSION_MODE_PARKED


def set_session_mode(
    conn: Any,
    session_id: str,
    mode: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist mode without touching heartbeat. Reason is parked-only."""
    row = _load_session(conn, session_id)
    if row.get("ended_at") is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    stored_mode = (mode or "").strip()
    if stored_mode not in SESSION_MODES:
        accepted = ", ".join(sorted(SESSION_MODES))
        raise SessionError(
            "UNKNOWN_MODE",
            f"unknown session mode {stored_mode!r}; accepted values: {accepted}",
        )
    stored_reason = (reason or "").strip() or None
    if stored_reason and stored_mode != SESSION_MODE_PARKED:
        raise SessionError(
            "REASON_REQUIRES_PARKED",
            "reason is only valid with mode parked",
        )
    if stored_mode == SESSION_MODE_PARKED and stored_reason is None:
        raise SessionError(
            "PARKED_REASON_REQUIRED",
            "mode parked requires a reason so the next reader knows why",
        )
    if stored_mode != SESSION_MODE_PARKED:
        stored_reason = None
    marker = _p(conn)
    if _parked_reason_present(conn):
        conn.execute(
            "UPDATE harness_sessions SET mode = "
            f"{marker}, parked_reason = {marker} "
            f"WHERE session_id = {marker}",
            (stored_mode, stored_reason, session_id),
        )
    else:
        conn.execute(
            f"UPDATE harness_sessions SET mode = {marker} WHERE session_id = {marker}",
            (stored_mode, session_id),
        )
    conn.commit()
    return _load_session(conn, session_id)


def clear_parked_mode(conn: Any, session_id: str) -> bool:
    """Explicit unpark back to wait. No-op when the session is not parked.

    Activity-state writers must skip fixtures that have no ``mode`` column.
    Tool-call telemetry does not call this; stamp a working mode to leave.
    """
    if not session_id:
        return False
    if "mode" not in _session_columns(conn):
        return False
    marker = _p(conn)
    if _parked_reason_present(conn):
        cursor = conn.execute(
            f"UPDATE harness_sessions SET mode = {marker}, "
            f"parked_reason = NULL WHERE session_id = {marker} "
            f"AND mode = {marker}",
            (SESSION_MODE_DEFAULT, session_id, SESSION_MODE_PARKED),
        )
    else:
        cursor = conn.execute(
            f"UPDATE harness_sessions SET mode = {marker} "
            f"WHERE session_id = {marker} AND mode = {marker}",
            (SESSION_MODE_DEFAULT, session_id, SESSION_MODE_PARKED),
        )
    return getattr(cursor, "rowcount", 0) > 0


__all__ = [
    "SESSION_MODES",
    "SESSION_MODE_DEFAULT",
    "SESSION_MODE_PARKED",
    "clear_parked_mode",
    "session_is_parked",
    "set_session_mode",
]

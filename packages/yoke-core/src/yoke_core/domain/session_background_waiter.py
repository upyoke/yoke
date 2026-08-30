"""One session's durable contract with a background watcher process.

Watcher wrappers already refresh their owning session once a minute while the
child is alive.  This module turns that pulse into an explicit deadline: the
wrapper arms a waiter before starting the child, token-bound liveness pulses
extend ``expected_by``, and the wrapper stamps completion when it exits.  A
killed wrapper leaves an overdue arm with no completion record instead of an
indistinguishable quiet session.  Unrelated session heartbeats cannot mask it.

Only one waiter is current for a session.  Re-arming replaces the old arm, and
completion is compare-by-id so a late old process cannot complete its
successor.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.session_liveness_pump import HEARTBEAT_INTERVAL_SECONDS
from yoke_core.domain.session_message_types import timestamp, utc_now
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_queries_base import _row_to_dict


BACKGROUND_WAITER_HEARTBEAT_GRACE_SECONDS = int(3 * HEARTBEAT_INTERVAL_SECONDS)
BACKGROUND_WAITER_COLUMNS = (
    "background_waiter_id",
    "background_waiter_kind",
    "background_waiter_fact",
    "background_waiter_armed_at",
    "background_waiter_expected_by",
    "background_waiter_completed_at",
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def background_waiter_columns_present(conn: Any) -> bool:
    """Whether this database has converged the additive waiter columns."""
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return False
    return set(BACKGROUND_WAITER_COLUMNS) <= columns


def _require_columns(conn: Any) -> None:
    if background_waiter_columns_present(conn):
        return
    raise SessionError(
        "BACKGROUND_WAITER_UNSUPPORTED",
        "This database has not converged the background-waiter session "
        "columns. Restart the serving build so boot convergence adds them, "
        "then re-arm the watcher.",
    )


def _load_session(conn: Any, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    return _row_to_dict(row)


def _deadline(now: datetime) -> str:
    return timestamp(now + timedelta(seconds=BACKGROUND_WAITER_HEARTBEAT_GRACE_SECONDS))


def _required(value: str, *, field: str, limit: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise SessionError(
            f"BACKGROUND_WAITER_{field.upper()}_REQUIRED",
            f"A background waiter must name its {field}. Re-run the watcher; "
            "the wrapper supplies this field automatically.",
        )
    if len(normalized) > limit:
        raise SessionError(
            f"BACKGROUND_WAITER_{field.upper()}_TOO_LONG",
            f"Background waiter {field} is limited to {limit} characters. "
            "Use a concise durable fact and re-arm the watcher.",
        )
    return normalized


def background_waiter_facts(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Project one row's current waiter contract, including completion."""
    if not row or not row.get("background_waiter_id"):
        return None
    completed_at = str(row.get("background_waiter_completed_at") or "") or None
    return {
        "waiter_id": str(row["background_waiter_id"]),
        "kind": str(row.get("background_waiter_kind") or ""),
        "watched_fact": str(row.get("background_waiter_fact") or ""),
        "armed_at": str(row.get("background_waiter_armed_at") or ""),
        "expected_by": str(row.get("background_waiter_expected_by") or ""),
        "completed_at": completed_at,
        "active": completed_at is None,
    }


def arm_background_waiter(
    conn: Any,
    session_id: str,
    *,
    waiter_id: str,
    kind: str,
    watched_fact: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Replace this session's current waiter with one live wrapper arm."""
    _require_columns(conn)
    row = _load_session(conn, session_id)
    if row.get("ended_at") is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    if row.get("terminated_at") is not None:
        raise SessionError(
            "SESSION_TERMINATED",
            f"Session '{session_id}' is permanently terminated. Launch a "
            "replacement session before starting another watcher.",
        )
    token = _required(waiter_id, field="id", limit=255)
    waiter_kind = _required(kind, field="kind", limit=80)
    fact = _required(watched_fact, field="fact", limit=500)
    current = now or utc_now()
    marker = _p(conn)
    conn.execute(
        f"""UPDATE harness_sessions
               SET background_waiter_id = {marker},
                   background_waiter_kind = {marker},
                   background_waiter_fact = {marker},
                   background_waiter_armed_at = {marker},
                   background_waiter_expected_by = {marker},
                   background_waiter_completed_at = NULL
             WHERE session_id = {marker}""",
        (token, waiter_kind, fact, timestamp(current), _deadline(current), session_id),
    )
    conn.commit()
    return background_waiter_facts(_load_session(conn, session_id)) or {}


def refresh_background_waiter_deadline(
    conn: Any,
    session_id: str,
    *,
    waiter_id: str,
    now: datetime | None = None,
) -> bool:
    """Extend the matching active waiter's deadline; caller owns commit."""
    _require_columns(conn)
    token = _required(waiter_id, field="id", limit=255)
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE harness_sessions SET background_waiter_expected_by = {marker} "
        f"WHERE session_id = {marker} AND background_waiter_id IS NOT NULL "
        f"AND background_waiter_id = {marker} "
        "AND background_waiter_completed_at IS NULL",
        (_deadline(now or utc_now()), session_id, token),
    )
    return getattr(cursor, "rowcount", 0) > 0


def pulse_background_waiter(
    conn: Any,
    session_id: str,
    *,
    waiter_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh one exact wrapper arm and return its compare-by-id receipt."""
    refreshed = refresh_background_waiter_deadline(
        conn,
        session_id,
        waiter_id=waiter_id,
        now=now,
    )
    conn.commit()
    facts = background_waiter_facts(_load_session(conn, session_id)) or {}
    return {**facts, "refreshed": refreshed}


def complete_background_waiter(
    conn: Any,
    session_id: str,
    *,
    waiter_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Stamp completion only when ``waiter_id`` is still the current arm."""
    _require_columns(conn)
    token = _required(waiter_id, field="id", limit=255)
    marker = _p(conn)
    cursor = conn.execute(
        f"UPDATE harness_sessions SET background_waiter_completed_at = {marker} "
        f"WHERE session_id = {marker} AND background_waiter_id = {marker} "
        "AND background_waiter_completed_at IS NULL",
        (timestamp(now or utc_now()), session_id, token),
    )
    conn.commit()
    facts = background_waiter_facts(_load_session(conn, session_id)) or {}
    return {**facts, "completed": getattr(cursor, "rowcount", 0) > 0}


__all__ = [
    "BACKGROUND_WAITER_COLUMNS",
    "BACKGROUND_WAITER_HEARTBEAT_GRACE_SECONDS",
    "arm_background_waiter",
    "background_waiter_columns_present",
    "background_waiter_facts",
    "complete_background_waiter",
    "pulse_background_waiter",
    "refresh_background_waiter_deadline",
]

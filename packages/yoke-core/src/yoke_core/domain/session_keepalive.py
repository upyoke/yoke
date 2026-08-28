"""Hold a claim-free session alive on purpose, against idle reaping.

A session that exists to be a wake target holds nothing by design: no work
claim, no document lock, no chain budget. Idle cleanup reads that emptiness as
"nothing would be lost" and ends the session, which is right for one that
merely finished and exactly wrong for one whose whole job is to still be there
when someone wakes it. The Fleet acceptance broker pair is the worked case:
two prepared sessions ended within seconds of their own last tool call, and
the run that had just prepared them re-read the roster and found nothing.

So the caller that needs the session says so, and says it with an expiry.

The hold is control-plane state, not a self-report. The session's own turns
neither set it nor clear it, which is the whole difference between this and
the parked mode a session declares about itself and its next tool call takes
back: a broker must survive precisely the turns the run makes it take. The
hold bounds itself, so a forgotten one costs a lease window rather than a
session that never leaves the roster. And it guards only *idle* reaping — an
explicit termination, and a machine that proves the process is gone, still end
the session, because a lease states an intent and those state a fact.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional, Sequence

from yoke_contracts.session_control.keepalive import (
    DEFAULT_KEEPALIVE_SECONDS,
    MAX_KEEPALIVE_SECONDS,
)
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    timestamp,
    utc_now,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_ended_recovery import session_ended_message
from yoke_core.domain.sessions_queries_base import _row_to_dict

KEEPALIVE_COLUMNS = ("keepalive_until", "keepalive_reason")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _keepalive_columns_present(conn: Any) -> bool:
    try:
        columns = set(_schema_get_columns(conn, "harness_sessions"))
    except db_backend.operational_error_types():
        return False
    return set(KEEPALIVE_COLUMNS) <= columns


def _load_session(conn: Any, session_id: str) -> Dict[str, Any]:
    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    return _row_to_dict(row)


def session_keepalive_facts(
    row: Mapping[str, Any] | None,
    *,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Return the live hold on this row, or ``None`` when none is in force.

    An expired hold is not a hold. Callers read this rather than the column so
    that "held" means the same thing to the end path, the roster projection,
    and the acceptance run verifying its own preparation.
    """
    if not row:
        return None
    until = parse_timestamp(row.get("keepalive_until"))
    if until is None or until <= (now or utc_now()):
        return None
    return {
        "keepalive_until": timestamp(until),
        "keepalive_reason": str(row.get("keepalive_reason") or "") or None,
    }


def session_keepalive_holds(
    conn: Any,
    session_ids: Sequence[str],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Dict[str, Any]]:
    """Name, per session, the hold still in force. Batched for the roster.

    The end path and the roster projection must agree: an operator reading
    "nothing blocking" while the hook refuses to end is how a real refusal
    becomes invisible, so both read the fleet through this one query.
    """
    targets = tuple(str(one) for one in session_ids if str(one or "").strip())
    if not targets or not _keepalive_columns_present(conn):
        return {}
    marker = _p(conn)
    placeholders = ",".join(marker for _ in targets)
    rows = conn.execute(
        "SELECT session_id, keepalive_until, keepalive_reason "
        f"FROM harness_sessions WHERE session_id IN ({placeholders}) "
        "AND keepalive_until IS NOT NULL",
        targets,
    ).fetchall()
    current = now or utc_now()
    held: Dict[str, Dict[str, Any]] = {}
    for raw in rows:
        row = _row_to_dict(raw)
        facts = session_keepalive_facts(row, now=current)
        if facts is not None:
            held[str(row["session_id"])] = facts
    return held


def hold_session_keepalive(
    conn: Any,
    session_id: str,
    *,
    seconds: int = DEFAULT_KEEPALIVE_SECONDS,
    reason: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Hold one live session against idle reaping until the lease expires.

    Re-holding an already-held session replaces the window, so a caller that
    needs longer renews rather than stacking leases it would have to unwind.
    """
    stated = (reason or "").strip()
    if not stated:
        raise SessionError(
            "KEEPALIVE_REASON_REQUIRED",
            "A keep-alive hold must say why the session must stay alive. "
            "Pass --reason with what is going to wake it.",
        )
    window = int(seconds)
    if window < 1 or window > MAX_KEEPALIVE_SECONDS:
        raise SessionError(
            "KEEPALIVE_WINDOW_INVALID",
            f"A keep-alive hold runs between 1 and "
            f"{MAX_KEEPALIVE_SECONDS} seconds; got {window}. "
            "Re-hold the session to extend it past that window.",
        )
    if not _keepalive_columns_present(conn):
        raise SessionError(
            "KEEPALIVE_UNSUPPORTED",
            "This database has no harness_sessions.keepalive_until column. "
            "Restart the server so its boot converges the schema, then retry.",
        )
    row = _load_session(conn, session_id)
    if row.get("ended_at") is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))
    if row.get("terminated_at") is not None:
        raise SessionError(
            "SESSION_TERMINATED",
            f"Session '{session_id}' was permanently terminated and cannot be "
            "held alive. Launch a replacement session instead.",
        )
    until = timestamp((now or utc_now()) + timedelta(seconds=window))
    marker = _p(conn)
    conn.execute(
        f"UPDATE harness_sessions SET keepalive_until = {marker}, "
        f"keepalive_reason = {marker} WHERE session_id = {marker}",
        (until, stated, session_id),
    )
    conn.commit()
    return _load_session(conn, session_id)


def release_session_keepalive(conn: Any, session_id: str) -> bool:
    """Drop any hold on this session. Reports whether one was in place."""
    if not session_id or not _keepalive_columns_present(conn):
        return False
    marker = _p(conn)
    cursor = conn.execute(
        "UPDATE harness_sessions SET keepalive_until = NULL, "
        f"keepalive_reason = NULL WHERE session_id = {marker} "
        "AND keepalive_until IS NOT NULL",
        (session_id,),
    )
    conn.commit()
    return getattr(cursor, "rowcount", 0) > 0


__all__ = [
    "KEEPALIVE_COLUMNS",
    "hold_session_keepalive",
    "release_session_keepalive",
    "session_keepalive_facts",
    "session_keepalive_holds",
]

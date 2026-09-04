"""Attach client-owned completion time to hook dispatch telemetry.

The hook client mints a correlation id before it runs, the dispatch row
carries that id in its own ``events.client_timing_id`` column, and the
client's completing report finds the row by that key inside a
minutes-wide window. Both bounds matter: the key makes a hit a single
index probe, and the window makes a miss — the ordinary outcome when the
row has not landed yet — cost nothing. The predecessor of this lookup
matched the id with ``envelope LIKE '%<id>%'`` over a thirty-day window
and scanned every telemetry row in it, which took the production
connection pool down for thirty-five minutes on 2026-09-04.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from yoke_contracts.hook_evaluator_protocol import HOOK_CLIENT_TIMING_ID_FIELD
from yoke_core.domain import db_backend
from yoke_core.domain.hook_observation_db_session import (
    apply_hook_observation_statement_timeout,
)


# How far back a completing report may reach for its dispatch row. The
# resident flushes its observation queue every two seconds, so this covers
# an ordinary report a thousand times over and leaves room for retry
# backoff; anything older is a report whose row was never written.
_LOOKBACK = timedelta(minutes=15)


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def _matching_event(conn: Any, event_id: str) -> Any | None:
    """Return the dispatch row for *event_id*, or ``None`` without scanning."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cutoff = (datetime.now(timezone.utc) - _LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = conn.execute(
        "SELECT id, duration_ms, envelope, session_id, actor_id, project_id FROM events "
        f"WHERE client_timing_id={marker} AND created_at >= {marker} LIMIT 1",
        (event_id, cutoff),
    ).fetchone()
    if row is None:
        return None
    try:
        envelope = json.loads(_value(row, "envelope", 2) or "{}")
    except (TypeError, ValueError):
        return None
    context = envelope.get("context") if isinstance(envelope, dict) else None
    if not isinstance(context, dict):
        return None
    return row, envelope, context


def _authorize(conn: Any, row: Any, actor_id: int | None) -> None:
    if actor_id is None:
        return
    stored_actor = _value(row, "actor_id", 4)
    if stored_actor is not None:
        if int(stored_actor) == int(actor_id):
            return
        raise PermissionError("hook telemetry belongs to another actor")
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    session = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={marker}",
        (str(_value(row, "session_id", 3) or ""),),
    ).fetchone()
    session_actor = _value(session, "actor_id", 0) if session is not None else None
    if session_actor is not None:
        if int(session_actor) == int(actor_id):
            return
        raise PermissionError("hook telemetry belongs to another actor")
    project_id = _value(row, "project_id", 5)
    if project_id is not None:
        from yoke_core.domain.actor_project_visibility import actor_visible_project_ids

        visible = actor_visible_project_ids(conn, actor_id) or set()
        if int(project_id) in {int(value) for value in visible}:
            return
    raise PermissionError("hook telemetry is outside the actor's visible projects")


def _apply_one_report(
    conn: Any,
    event_id: str,
    reported_ms: int,
    actor_id: int | None,
) -> None:
    """Complete one dispatch row, holding no lock across the lookup.

    The read commits before the update opens, so a row lock is never held
    while another statement is still reading.
    """
    match = _matching_event(conn, event_id)
    conn.commit()
    if match is None:
        return
    row, envelope, context = match
    _authorize(conn, row, actor_id)
    duration_ms = max(0, int(_value(row, "duration_ms", 1) or 0))
    hook_wait_ms = max(0, int(context.get("hook_wait_ms") or 0))
    context["client_wall_ms"] = max(duration_ms, hook_wait_ms, max(0, int(reported_ms)))
    context.pop(HOOK_CLIENT_TIMING_ID_FIELD, None)
    envelope["context"] = context
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE events SET envelope={marker}, client_timing_id=NULL WHERE id={marker}",
        (json.dumps(envelope, separators=(",", ":")), _value(row, "id", 0)),
    )
    conn.commit()


def record_client_wall_reports(
    reports: Iterable[tuple[str, int]],
    *,
    actor_id: int | None = None,
) -> int:
    """Apply idempotent reports; absent best-effort telemetry is accepted."""
    conn = db_backend.connect()
    accepted = 0
    try:
        apply_hook_observation_statement_timeout(conn)
        for event_id, reported_ms in reports:
            _apply_one_report(conn, event_id, reported_ms, actor_id)
            accepted += 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return accepted


__all__ = ["record_client_wall_reports"]

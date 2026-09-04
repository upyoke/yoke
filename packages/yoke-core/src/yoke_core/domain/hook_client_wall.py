"""Attach client-owned completion time to hook dispatch telemetry."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from yoke_core.domain import db_backend


_EVENT_NAME = "HookDispatchTelemetry"
_LOOKBACK = timedelta(days=30)


def _value(row: Any, key: str, index: int) -> Any:
    return row.get(key) if isinstance(row, dict) else row[index]


def _matching_event(conn: Any, event_id: str) -> Any | None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    cutoff = (datetime.now(timezone.utc) - _LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT id, duration_ms, envelope, session_id, actor_id, project_id FROM events "
        f"WHERE event_name={marker} AND created_at >= {marker} "
        f"AND envelope LIKE {marker} ORDER BY created_at DESC LIMIT 8",
        (_EVENT_NAME, cutoff, f"%{event_id}%"),
    ).fetchall()
    for row in rows:
        try:
            envelope = json.loads(_value(row, "envelope", 2) or "{}")
        except (TypeError, ValueError):
            continue
        context = envelope.get("context") if isinstance(envelope, dict) else None
        if isinstance(context, dict) and context.get("client_timing_id") == event_id:
            return row, envelope, context
    return None


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


def record_client_wall_reports(
    reports: Iterable[tuple[str, int]],
    *,
    actor_id: int | None = None,
) -> int:
    """Apply idempotent reports; absent best-effort telemetry is accepted."""
    conn = db_backend.connect()
    accepted = 0
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        for event_id, reported_ms in reports:
            match = _matching_event(conn, event_id)
            if match is None:
                accepted += 1
                continue
            row, envelope, context = match
            _authorize(conn, row, actor_id)
            duration_ms = max(0, int(_value(row, "duration_ms", 1) or 0))
            hook_wait_ms = max(0, int(context.get("hook_wait_ms") or 0))
            context["client_wall_ms"] = max(
                duration_ms, hook_wait_ms, max(0, int(reported_ms))
            )
            context.pop("client_timing_id", None)
            envelope["context"] = context
            conn.execute(
                f"UPDATE events SET envelope={marker} WHERE id={marker}",
                (json.dumps(envelope, separators=(",", ":")), _value(row, "id", 0)),
            )
            accepted += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return accepted


__all__ = ["record_client_wall_reports"]

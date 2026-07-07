"""Session-lifecycle command handlers (begin/touch/end/get).

These are the small mutators that begin a harness session, refresh its
heartbeat, end it (delegating to the canonical guarded end-session
path), and read a single row by session id.
"""

from __future__ import annotations

import json
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.sessions import SessionError, end_session
from yoke_core.domain.sessions_lifecycle_canonicalize import canonicalize_executor

from runtime.harness.harness_sessions_event_emit import _emit_event
from runtime.harness.harness_sessions_focus import (
    _format_row,
    _now_iso,
    _require_active_session,
)


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def cmd_begin(
    conn,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    lane: str = "primary",
    mode: str = "wait",
) -> str:
    now = _now_iso()
    p = _placeholder(conn)
    canonical_executor, display_name = canonicalize_executor(executor, None)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, executor_display_name, provider, model, "
        "execution_lane, capabilities, workspace, mode, offered_at, "
        "last_heartbeat) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, '[]', {p}, {p}, {p}, {p})",
        (
            session_id, canonical_executor, display_name, provider, model,
            lane, workspace, mode, now, now,
        ),
    )
    conn.commit()
    event_payload = {
        "executor": canonical_executor,
        "provider": provider,
        "model": model,
        "workspace": workspace,
    }
    if display_name:
        event_payload["executor_display_name"] = display_name
    _emit_event(
        conn,
        session_id,
        "HarnessSessionStarted",
        json.dumps(event_payload),
    )
    return f"Began session: {session_id}"


def cmd_touch(conn, session_id: str, mode: Optional[str] = None) -> str:
    now = _now_iso()
    p = _placeholder(conn)
    _require_active_session(conn, session_id)
    conn.execute(
        f"UPDATE harness_sessions SET last_heartbeat={p} WHERE session_id={p}",
        (now, session_id),
    )
    conn.execute(
        f"UPDATE work_claims SET last_heartbeat={p} "
        f"WHERE session_id={p} AND released_at IS NULL",
        (now, session_id),
    )
    if mode:
        conn.execute(
            f"UPDATE harness_sessions SET mode={p} WHERE session_id={p}",
            (mode, session_id),
        )
    conn.commit()
    return f"Heartbeat updated: {session_id}"


def cmd_end(conn, session_id: str, force: bool = False) -> str:
    try:
        end_session(conn, session_id, force=force)
    except SessionError as exc:
        if exc.code == "CHAIN_PENDING":
            raise PermissionError("Session has pending chain work. Use --force to end anyway.")
        if exc.code in {"NOT_FOUND", "SESSION_ENDED"}:
            raise LookupError(exc.message)
        raise RuntimeError(exc.message) from exc
    return f"Session ended: {session_id}"


def cmd_get(conn, session_id: str) -> str:
    p = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT session_id, executor, provider, model, execution_lane, "
        "capabilities, workspace, mode, offered_at, last_heartbeat, "
        "COALESCE(ended_at, '') "
        f"FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    )
    if row is None:
        raise LookupError(f"session '{session_id}' not found")
    return _format_row(row)

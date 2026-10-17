"""Session-lifecycle command handlers (begin/touch/end/get).

These are the small mutators that begin a harness session, refresh its
heartbeat, end it (delegating to the canonical guarded end-session
path), and read a single row by session id.
"""

from __future__ import annotations

import json

from yoke_contracts.timestamps import utc_now
from yoke_contracts.session_model_facts import (
    SessionModelFacts,
    normalize_reasoning_effort,
)
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter, query_one
from yoke_core.domain.sessions import SessionError, end_session
from yoke_core.domain.sessions_lifecycle_canonicalize import canonicalize_executor
from yoke_core.domain.session_scope_identity import resolve_registration_scope
from yoke_core.domain.sessions_lifecycle_identity import resolve_session_actor_id
from yoke_core.domain.sessions_registration_write import insert_registration
from yoke_core.domain.session_activity_state import (
    episode_column_present,
    native_thread_id_column_present,
)

from yoke_core.hooks.sessions_event_emit import _emit_event
from yoke_core.hooks.sessions_focus import (
    _format_row,
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
    level: str = "primary",
    mode: str = "wait",
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    *,
    project_id: int | None,
    reasoning_effort: str | None = None,
) -> str:
    """Begin a session with an authenticated actor and exclusive stored scope."""
    now = instant_parameter(conn, utc_now())
    p = _placeholder(conn)
    canonical_executor, display_name = canonicalize_executor(executor, None)
    effort = normalize_reasoning_effort(reasoning_effort)
    if reasoning_effort is not None and effort is None:
        raise ValueError("Unknown reasoning effort; use a supported harness effort.")
    actor_id = resolve_session_actor_id(conn, None)
    scope = resolve_registration_scope(
        conn, actor_id=actor_id, project_id=project_id, machine_scope=project_id is None
    )
    insert_registration(
        conn,
        placeholder=p,
        session_id=session_id,
        executor=canonical_executor,
        surface=display_name,
        executor_version=executor_version,
        machine_id=machine_id,
        provider=provider,
        model_facts=SessionModelFacts(model=model, reasoning_effort=effort),
        execution_level=level,
        workspace=workspace,
        mode=mode,
        now=now,
        envelope_json=None,
        actor_id=actor_id,
        scope=scope,
        native_thread_id=None,
        has_native_thread=native_thread_id_column_present(conn),
        has_episode=episode_column_present(conn),
    )
    conn.commit()
    event_payload = {
        "executor": canonical_executor,
        "provider": provider,
        "model": model,
        "workspace": workspace,
    }
    if display_name:
        event_payload["executor_surface"] = display_name
    if executor_version:
        event_payload["executor_version"] = executor_version
    if machine_id:
        event_payload["machine_id"] = machine_id
    _emit_event(
        conn,
        session_id,
        "HarnessSessionStarted",
        json.dumps(event_payload),
    )
    return f"Began session: {session_id}"


def cmd_touch(conn, session_id: str, mode: Optional[str] = None) -> str:
    now = instant_parameter(conn, utc_now())
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
        if exc.code in {"NOT_FOUND", "SESSION_ENDED"}:
            raise LookupError(exc.message)
        raise RuntimeError(exc.message) from exc
    return f"Session ended: {session_id}"


def cmd_get(conn, session_id: str) -> str:
    p = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT session_id, executor, executor_surface, executor_version, "
        "machine_id, provider, model, execution_level, workspace, mode, "
        "offered_at, last_heartbeat, "
        "ended_at "
        f"FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    )
    if row is None:
        raise LookupError(f"session '{session_id}' not found")
    return _format_row(row)

"""Session registration, heartbeat, and mode mutations."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .session_activity_state import episode_column_present
from .sessions_analytics import EVENT_HARNESS_SESSION_STARTED, SessionError
from .sessions_lifecycle_canonicalize import canonicalize_executor as _canonicalize_executor
from .sessions_lifecycle_identity import (
    DEFAULT_EXECUTION_LANE,
    refresh_active_duplicate_identity,
    resolve_reactivation_identity,
)
from .sessions_lifecycle_reactivation import emit_reactivated_with_released_claims
from .sessions_queries import _now_iso, _row_to_dict


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _get_session(conn: Any, session_id: str) -> Dict[str, Any]:
    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    d = _row_to_dict(row)
    if d.get("capabilities"):
        try:
            d["capabilities"] = json.loads(d["capabilities"])
        except (json.JSONDecodeError, TypeError):
            pass
    if d.get("offer_envelope"):
        try:
            d["offer_envelope"] = json.loads(d["offer_envelope"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def _get_claim(conn: Any, claim_id: int) -> Dict[str, Any]:
    row = conn.execute(
        f"SELECT * FROM work_claims WHERE id = {_p(conn)}",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Claim {claim_id} not found.")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Session registration
# ---------------------------------------------------------------------------


def _resolve_session_actor_id(
    conn: Any,
    explicit: Optional[int],
) -> Optional[int]:
    """Validate an explicit actor id for ``harness_sessions.actor_id``.

    Actor identity is session/auth-bound: callers that know the actor
    (the token-auth boundary, operator tooling) pass it explicitly and
    it is honoured after a presence check on the ``actors`` table.
    Without an explicit actor the row stores NULL — the shape
    https-registered sessions already carry — and downstream readers
    resolve actors through their own session/auth ladders.
    """
    if explicit is None:
        return None
    try:
        from yoke_core.domain.actors import validate_actor_id
        if validate_actor_id(conn, int(explicit)):
            return int(explicit)
    except db_backend.operational_error_types(conn) + (ValueError,):
        return None
    return None


def _resolve_session_project_id(
    conn: Any,
    explicit: int,
) -> int:
    if explicit is None:
        raise SessionError(
            "PROJECT_ID_REQUIRED",
            "Session registration requires a resolved project_id.",
        )
    try:
        project_id = int(explicit)
    except (TypeError, ValueError):
        raise SessionError(
            "PROJECT_ID_INVALID",
            "Session registration project_id must be a positive integer.",
        )
    if project_id <= 0:
        raise SessionError(
            "PROJECT_ID_INVALID",
            "Session registration project_id must be a positive integer.",
        )
    try:
        found = conn.execute(
            f"SELECT 1 FROM projects WHERE id = {_p(conn)}",
            (project_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        raise SessionError(
            "PROJECTS_TABLE_REQUIRED",
            "Session registration requires the projects table.",
        )
    if not found:
        raise SessionError(
            "PROJECT_NOT_FOUND",
            f"Session registration project_id {project_id} was not found.",
        )
    return project_id


def register_session(
    conn: Any,
    *,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    execution_lane: str = DEFAULT_EXECUTION_LANE,
    capabilities: Optional[List[str]] = None,
    workspace: str,
    project_id: int,
    mode: str = "wait",
    offer_envelope: Optional[Dict[str, Any]] = None,
    entrypoint: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Register a new active session."""
    now = _now_iso()
    caps_json = json.dumps(capabilities or [])
    envelope_json = json.dumps(offer_envelope) if offer_envelope else None
    resolved_actor_id = _resolve_session_actor_id(conn, actor_id)
    resolved_project_id = _resolve_session_project_id(conn, project_id)
    canonical_executor, display_name = _canonicalize_executor(executor, entrypoint)
    p = _p(conn)
    # episode_started_at marks the current-episode boundary (fresh start
    # AND reactivation); introspection tolerates minimal fixtures.
    has_episode_col = episode_column_present(conn)
    insert_cols = (
        "session_id, executor, executor_display_name, provider, model, "
        "execution_lane, capabilities, workspace, mode, offered_at, "
        "last_heartbeat, ended_at, offer_envelope, actor_id, project_id"
    )
    insert_values: List[Any] = [
        session_id, canonical_executor, display_name, provider, model,
        execution_lane, caps_json, workspace, mode, now, now,
        None, envelope_json, resolved_actor_id, resolved_project_id,
    ]
    if has_episode_col:
        insert_cols += ", episode_started_at"
        insert_values.append(now)
    insert_placeholders = ", ".join([p] * len(insert_values))

    try:
        conn.execute(
            f"INSERT INTO harness_sessions ({insert_cols}) "
            f"VALUES ({insert_placeholders})",
            tuple(insert_values),
        )
        conn.commit()
    except db_backend.integrity_error_types():
        # Postgres poisons the transaction after the duplicate INSERT; SQLite
        # does not, so only the native PG path rolls back before reactivation.
        if db_backend.connection_is_postgres(conn):
            conn.rollback()
        existing = conn.execute(
            f"SELECT ended_at, model, actor_id, execution_lane, project_id "
            f"FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if existing is None or existing["ended_at"] is None:
            refresh_active_duplicate_identity(
                conn,
                placeholder=p,
                existing=existing,
                session_id=session_id,
                model=model,
                execution_lane=execution_lane,
                actor_id=actor_id,
                resolved_actor_id=resolved_actor_id,
            )
            raise SessionError(
                "SESSION_EXISTS",
                f"Session '{session_id}' is already registered.",
            )

        resolved_model, resolved_lane = resolve_reactivation_identity(
            existing, model=model, execution_lane=execution_lane,
        )
        explicit_overwrite = actor_id is not None and resolved_actor_id is not None
        implicit_backfill = actor_id is None and resolved_actor_id is not None

        if explicit_overwrite:
            actor_clause = f", actor_id = {p}"
        elif implicit_backfill:
            actor_clause = f", actor_id = COALESCE(actor_id, {p})"
        else:
            actor_clause = ""

        episode_clause = (
            f", episode_started_at = {p}" if has_episode_col else ""
        )
        params: List[Any] = [
            provider,
            resolved_model,
            resolved_lane,
            caps_json,
            workspace,
            mode,
            now,
            envelope_json,
        ]
        if episode_clause:
            params.append(now)
        if actor_clause:
            params.append(resolved_actor_id)
        project_clause = f", project_id = {p}"
        params.append(resolved_project_id)
        params.append(session_id)

        cursor = conn.execute(
            f"""UPDATE harness_sessions
               SET provider = {p},
                   model = {p},
                   execution_lane = {p},
                   capabilities = {p},
                   workspace = {p},
                   mode = {p},
                   last_heartbeat = {p},
                   ended_at = NULL,
                   offer_envelope = {p}{episode_clause}{actor_clause}{project_clause}
               WHERE session_id = {p} AND ended_at IS NOT NULL""",
            tuple(params),
        )
        if getattr(cursor, "rowcount", 1) == 0:
            raise SessionError(
                "SESSION_EXISTS",
                f"Session '{session_id}' is already registered.",
            )
        conn.commit()
        # Reactivation surfaces prior session-ended claims and conditionally
        # auto-reacquires targets that have no active conflicting holder.
        try:
            emit_reactivated_with_released_claims(conn, session_id)
        except Exception:
            pass  # telemetry — never block reactivation
        model = resolved_model  # reflect the stored value in the event
        execution_lane = resolved_lane

    # Report the stored executor value (which may differ from
    # the call argument when re-registering a closed session under the same
    # session_id, since executor is write-once).  Executor stores the
    # canonical harness_id enum; executor_display_name carries the
    # surface-specific alias when known.  Both fields are write-once on
    # re-register so attribution stays stable across the session.
    stored_row = conn.execute(
        "SELECT executor, executor_display_name FROM harness_sessions "
        f"WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    stored_executor = (
        stored_row["executor"] if stored_row is not None else canonical_executor
    )
    stored_display = (
        stored_row["executor_display_name"]
        if stored_row is not None
        else display_name
    )

    event_context: Dict[str, Any] = {
        "executor": stored_executor,
        "provider": provider,
        "model": model,
        "execution_lane": execution_lane,
        "workspace": workspace,
        "mode": mode,
    }
    if stored_display:
        event_context["executor_display_name"] = stored_display
    event_context["project_id"] = resolved_project_id
    if entrypoint:
        event_context["entrypoint"] = entrypoint
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_STARTED,
        session_id=session_id,
        context=event_context,
    )

    return _get_session(conn, session_id)


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


def heartbeat(conn: Any, session_id: str) -> Dict[str, Any]:
    """Update last_heartbeat on a session and all its active claims.

    Raises SessionError if the session does not exist or has ended.
    """
    now = _now_iso()

    row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row["ended_at"] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    conn.execute(
        f"UPDATE harness_sessions SET last_heartbeat = {_p(conn)} "
        f"WHERE session_id = {_p(conn)}",
        (now, session_id),
    )
    conn.execute(
        f"UPDATE work_claims SET last_heartbeat = {_p(conn)} "
        f"WHERE session_id = {_p(conn)} AND released_at IS NULL",
        (now, session_id),
    )
    conn.commit()

    return _get_session(conn, session_id)


# ---------------------------------------------------------------------------
# Session mode
# ---------------------------------------------------------------------------


def set_session_mode(
    conn: Any,
    session_id: str,
    mode: str,
) -> Dict[str, Any]:
    """Persist the current session mode without changing heartbeat state."""
    row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row["ended_at"] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    conn.execute(
        f"UPDATE harness_sessions SET mode = {_p(conn)} WHERE session_id = {_p(conn)}",
        (mode, session_id),
    )
    conn.commit()

    return _get_session(conn, session_id)

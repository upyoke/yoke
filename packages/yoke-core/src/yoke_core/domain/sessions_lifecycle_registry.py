"""Session registration, heartbeat, and mode mutations."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_contracts.session_lane import UNRESOLVED_EXECUTION_LANE
from . import db_backend
from . import sessions_analytics as _sa
from .session_activity_state import (
    episode_column_present,
    native_thread_id_column_present,
)
from .sessions_analytics import EVENT_HARNESS_SESSION_STARTED, SessionError
from .sessions_ended_recovery import session_ended_message
from .sessions_lifecycle_canonicalize import (
    canonicalize_executor as _canonicalize_executor,
)
from .sessions_lifecycle_identity import (
    normalize_observed_identity,
    record_reactivation_wake_driver,
    refresh_active_duplicate_identity,
    resolve_reactivation_executor_version,
    resolve_reactivation_identity,
    resolve_session_actor_id,
    resolve_session_project_id,
)
from .sessions_lifecycle_reactivation import emit_reactivated_with_released_claims
from .sessions_queries import _now_iso, _row_to_dict
from .work_claim_targets import from_row as target_from_row


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
    claim = _row_to_dict(row)
    claim["scope"] = dict(target_from_row(claim).scope)
    return claim


def register_session(
    conn: Any,
    *,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    execution_lane: str = UNRESOLVED_EXECUTION_LANE,
    workspace: str,
    project_id: int,
    mode: str = "wait",
    offer_envelope: Optional[Dict[str, Any]] = None,
    entrypoint: Optional[str] = None,
    actor_id: Optional[int] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    native_thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new active session.

    ``native_thread_id`` is the harness's own thread/session identity
    (currently Codex's ``CODEX_THREAD_ID``) when the environment or a
    relayed hook payload carries it — distinct from ``session_id``, which
    an operator-started session may register under a different value.
    Wake resolves against this column instead of assuming the two agree.
    """
    now = _now_iso()
    envelope_json = json.dumps(offer_envelope) if offer_envelope else None
    resolved_actor_id = resolve_session_actor_id(conn, actor_id)
    resolved_project_id = resolve_session_project_id(conn, project_id)
    executor_version, machine_id = normalize_observed_identity(
        executor_version, machine_id
    )
    canonical_executor, display_name = _canonicalize_executor(executor, entrypoint)
    p = _p(conn)
    # episode_started_at marks the current-episode boundary (fresh start
    # AND reactivation); introspection tolerates minimal fixtures.
    has_episode_col = episode_column_present(conn)
    has_thread_col = native_thread_id_column_present(conn)
    insert_cols = (
        "session_id, executor, executor_surface, executor_version, machine_id, "
        "provider, model, execution_lane, workspace, mode, offered_at, "
        "last_heartbeat, ended_at, offer_envelope, actor_id, project_id"
    )
    # fmt: off
    insert_values: List[Any] = [
        session_id, canonical_executor, display_name, executor_version, machine_id,
        provider, model, execution_lane, workspace, mode, now, now,
        None, envelope_json, resolved_actor_id, resolved_project_id,
    ]
    # fmt: on
    if has_thread_col:
        insert_cols += ", native_thread_id"
        insert_values.append(native_thread_id)
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
        thread_select = ", native_thread_id" if has_thread_col else ""
        existing = conn.execute(
            f"SELECT ended_at, terminated_at, model, actor_id, execution_lane, project_id, "
            f"executor_version, machine_id, executor_surface{thread_select} "
            f"FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if existing is not None and existing["terminated_at"] is not None:
            raise SessionError(
                "SESSION_TERMINATED",
                f"Session '{session_id}' is permanently terminated.",
            )
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
                executor_surface=display_name,
                executor_version=executor_version,
                machine_id=machine_id,
                native_thread_id=native_thread_id if has_thread_col else None,
            )
            raise SessionError(
                "SESSION_EXISTS",
                f"Session '{session_id}' is already registered.",
            )

        resolved_model, resolved_lane = resolve_reactivation_identity(
            existing, model=model, execution_lane=execution_lane
        )
        driver_version = executor_version
        executor_version = resolve_reactivation_executor_version(
            existing, incoming_surface=display_name, incoming_version=driver_version
        )
        explicit_overwrite = actor_id is not None and resolved_actor_id is not None
        implicit_backfill = actor_id is None and resolved_actor_id is not None

        if explicit_overwrite:
            actor_clause = f", actor_id = {p}"
        elif implicit_backfill:
            actor_clause = f", actor_id = COALESCE(actor_id, {p})"
        else:
            actor_clause = ""

        episode_clause = f", episode_started_at = {p}" if has_episode_col else ""
        thread_clause = (
            f", native_thread_id = COALESCE({p}, native_thread_id)"
            if has_thread_col
            else ""
        )
        # fmt: off
        params: List[Any] = [
            provider, resolved_model, resolved_lane, workspace, mode, now,
            envelope_json, executor_version, machine_id,
        ]
        # fmt: on
        if thread_clause:
            params.append(native_thread_id)
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
                   workspace = {p},
                   mode = {p},
                   last_heartbeat = {p},
                   ended_at = NULL,
                   offer_envelope = {p},
                   executor_version = {p},
                   machine_id = {p}
                   {thread_clause}{episode_clause}{actor_clause}{project_clause}
               WHERE session_id = {p} AND ended_at IS NOT NULL""",
            tuple(params),
        )
        if getattr(cursor, "rowcount", 1) == 0:
            raise SessionError(
                "SESSION_EXISTS",
                f"Session '{session_id}' is already registered.",
            )
        conn.commit()
        record_reactivation_wake_driver(
            conn,
            session_id=session_id,
            driver_surface=display_name,
            driver_version=driver_version,
        )
        # Reactivation surfaces prior session-ended claims and conditionally
        # auto-reacquires targets that have no active conflicting holder.
        try:
            emit_reactivated_with_released_claims(conn, session_id)
        except Exception:
            pass  # telemetry — never block reactivation
        model = resolved_model  # reflect the stored value in the event
        execution_lane = resolved_lane

    # Stored executor/surface are write-once across reactivation. Version
    # stays paired with the stored surface unless the same surface returns.
    stored_row = conn.execute(
        "SELECT executor, executor_surface FROM harness_sessions "
        f"WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    stored_executor = (
        stored_row["executor"] if stored_row is not None else canonical_executor
    )
    stored_display = (
        stored_row["executor_surface"] if stored_row is not None else display_name
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
        event_context["executor_surface"] = stored_display
    if executor_version:
        event_context["executor_version"] = executor_version
    if machine_id:
        event_context["machine_id"] = machine_id
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
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))

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
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))

    conn.execute(
        f"UPDATE harness_sessions SET mode = {_p(conn)} WHERE session_id = {_p(conn)}",
        (mode, session_id),
    )
    conn.commit()

    return _get_session(conn, session_id)

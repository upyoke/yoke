"""Session registration, heartbeat, and mode mutations."""

from __future__ import annotations
from .session_execution_level_write import refresh_session_execution_level

import json
from yoke_contracts.timestamps import utc_now
from .db_helpers import instant_parameter

from typing import Any, Dict, List, Optional

from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL
from yoke_contracts.session_model_facts import SessionModelFacts
from . import db_backend
from . import sessions_analytics as _sa
from .session_activity_state import (
    episode_column_present,
    native_thread_id_column_present,
)
from .sessions_analytics import EVENT_HARNESS_SESSION_STARTED, SessionError
from .session_mode import set_session_mode as set_session_mode
from .sessions_ended_recovery import session_ended_message
from .sessions_lifecycle_canonicalize import (
    canonicalize_executor as _canonicalize_executor,
)
from .session_model_columns import merged_facts
from .session_scope_identity import resolve_registration_scope
from .sessions_registration_write import insert_registration, reactivate_registration
from .sessions_lifecycle_identity import (
    existing_registration_row,
    normalize_observed_identity,
    refresh_active_duplicate_identity,
    resolve_reactivation_executor_version,
    resolve_session_actor_id,
)
from .sessions_lifecycle_reactivation import emit_reactivated_with_released_claims
from .sessions_started_event import session_started_context
from .sessions_reactivation_driver import (
    build_reactivation_driver_stamp,
    record_reactivation_wake_driver,
)
from .sessions_queries import _row_to_dict
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
    model_facts: SessionModelFacts,
    execution_level: str = UNRESOLVED_EXECUTION_LEVEL,
    workspace: str,
    project_id: int | None,
    machine_scope: bool = False,
    mode: str = "wait",
    offer_envelope: Optional[Dict[str, Any]] = None,
    entrypoint: Optional[str] = None,
    actor_id: Optional[int] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    native_thread_id: Optional[str] = None,
    driver: Optional[Dict[str, Any]] = None,
    launch_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new active session.

    ``launch_id`` binds the launching actor rather than the operating
    actor of the machine running the session, and is authoritative the
    way an explicit actor is: a reactivation overwrites with it.

    ``model_facts`` carries the requested ask beside whatever a provider
    attested; ``session_model_columns`` owns how each half is written.

    ``driver`` is the process that drove this call — pid, ppid, and the hook
    event behind it — resolved by the hook dispatch tail. A reactivation
    stamps it on its ``HarnessSessionStarted`` context unconditionally, so
    "which process revived this session, and what hook event drove it" is
    answerable from stored rows for every reactivation. It is deliberately
    not stamped on a fresh registration: there the driving surface and the
    registered surface are the same row, whereas a reactivation can be driven
    across surfaces (a CLI hook reviving a desktop session) and the two facts
    genuinely differ.

    ``native_thread_id`` is the harness's own thread/session identity
    (Codex's ``CODEX_THREAD_ID``) when the environment or a relayed hook
    payload carries it — distinct from ``session_id``, which an
    manually started session may register under a different value. Wake
    resolves against that column rather than assuming the two agree.
    """
    now = instant_parameter(conn, utc_now())
    envelope_json = json.dumps(offer_envelope) if offer_envelope else None
    resolved_actor_id = resolve_session_actor_id(conn, actor_id, launch_id=launch_id)
    scope = resolve_registration_scope(
        conn,
        actor_id=resolved_actor_id,
        project_id=project_id,
        machine_scope=machine_scope,
    )
    executor_version, machine_id = normalize_observed_identity(
        executor_version, machine_id
    )
    canonical_executor, display_name = _canonicalize_executor(executor, entrypoint)
    p = _p(conn)
    # episode_started_at marks the current-episode boundary (fresh start
    # AND reactivation); introspection tolerates minimal fixtures.
    has_episode_col = episode_column_present(conn)
    has_thread_col = native_thread_id_column_present(conn)
    # Populated only on the reactivation branch below; a fresh insert leaves
    # the event context untouched.
    reactivation_driver: Dict[str, Any] = {}
    # Reactivation folds the reading into what the row already proved.
    resolved_facts = model_facts

    try:
        insert_registration(
            conn,
            placeholder=p,
            session_id=session_id,
            executor=canonical_executor,
            surface=display_name,
            executor_version=executor_version,
            machine_id=machine_id,
            provider=provider,
            model_facts=model_facts,
            execution_level=execution_level,
            workspace=workspace,
            mode=mode,
            now=now,
            envelope_json=envelope_json,
            actor_id=resolved_actor_id,
            scope=scope,
            native_thread_id=native_thread_id,
            has_native_thread=has_thread_col,
            has_episode=has_episode_col,
        )
        execution_level = refresh_session_execution_level(conn, session_id)
        conn.commit()
    except db_backend.integrity_error_types():
        # Postgres poisons the transaction after the duplicate INSERT; SQLite
        # does not, so only the native PG path rolls back before reactivation.
        if db_backend.connection_is_postgres(conn):
            conn.rollback()
        existing = existing_registration_row(
            conn,
            placeholder=p,
            session_id=session_id,
            include_native_thread=has_thread_col,
        )
        if existing is not None and existing["terminated_at"] is not None:
            raise SessionError(
                "SESSION_TERMINATED",
                f"Session '{session_id}' is permanently terminated.",
            )
        if (
            existing is not None
            and existing["project_id"] is not None
            and scope.project_id is not None
            and existing["project_id"] != scope.project_id
        ):
            raise SessionError(
                "SESSION_SCOPE_IMMUTABLE",
                "A session cannot change its registered project. Recovery: open a new session in that folder.",
            )
        if existing is None or existing["ended_at"] is None:
            refresh_active_duplicate_identity(
                conn,
                placeholder=p,
                existing=existing,
                session_id=session_id,
                model_facts=model_facts,
                execution_level=execution_level,
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

        resolved_facts = merged_facts(existing, model_facts)
        resolved_level = execution_level
        driver_version = executor_version
        executor_version = resolve_reactivation_executor_version(
            existing, incoming_surface=display_name, incoming_version=driver_version
        )
        # Registration/reactivation is a probe, not session activity.
        cursor = reactivate_registration(
            conn,
            placeholder=p,
            session_id=session_id,
            provider=provider,
            model_facts=resolved_facts,
            execution_level=resolved_level,
            workspace=workspace,
            mode=mode,
            envelope_json=envelope_json,
            executor_version=executor_version,
            machine_id=machine_id,
            native_thread_id=native_thread_id,
            now=now,
            actor_id=resolved_actor_id,
            replace_actor=actor_id is not None or bool(launch_id),
            has_native_thread=has_thread_col,
            has_episode=has_episode_col,
        )
        if getattr(cursor, "rowcount", 1) == 0:
            raise SessionError(
                "SESSION_EXISTS",
                f"Session '{session_id}' is already registered.",
            )
        resolved_level = refresh_session_execution_level(conn, session_id)
        conn.commit()
        reactivation_driver = build_reactivation_driver_stamp(
            driver_surface=display_name,
            driver_version=driver_version,
            driver=driver,
        )
        # The wake-attempt evidence row keeps its stamp where an attempt is
        # in flight, built from the SAME resolved facts as the event context
        # below — the two records agree rather than reporting separately.
        record_reactivation_wake_driver(
            conn,
            session_id=session_id,
            driver_surface=display_name,
            driver_version=driver_version,
            driver=driver,
        )
        # Reactivation surfaces prior session-ended claims and conditionally
        # auto-reacquires targets that have no active conflicting holder.
        try:
            emit_reactivated_with_released_claims(conn, session_id)
        except Exception:
            pass  # telemetry — never block reactivation
        execution_level = resolved_level

    event_context = session_started_context(
        conn,
        placeholder=p,
        session_id=session_id,
        fallback_executor=canonical_executor,
        fallback_surface=display_name,
        provider=provider,
        model_facts=resolved_facts,
        execution_level=execution_level,
        workspace=workspace,
        mode=mode,
        executor_version=executor_version,
        machine_id=machine_id,
        project_id=scope.project_id,
        entrypoint=entrypoint,
        reactivation_driver=reactivation_driver,
    )
    _sa._emit_session_event(
        EVENT_HARNESS_SESSION_STARTED,
        session_id=session_id,
        context=event_context,
    )

    return _get_session(conn, session_id)


def heartbeat(
    conn: Any,
    session_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Update the heartbeat, optional quiet reason, and active claims.

    Raises SessionError if the session does not exist or has ended.
    """
    now = instant_parameter(conn, utc_now())

    row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if row["ended_at"] is not None:
        raise SessionError("SESSION_ENDED", session_ended_message(conn, session_id))

    assignments = f"last_heartbeat = {_p(conn)}"
    values: List[Any] = [now]
    if reason is not None:
        assignments += f", quiet_reason = {_p(conn)}"
        values.append(reason.strip() or None)
    conn.execute(
        f"UPDATE harness_sessions SET {assignments} WHERE session_id = {_p(conn)}",
        (*values, session_id),
    )
    conn.execute(
        f"UPDATE work_claims SET last_heartbeat = {_p(conn)} "
        f"WHERE session_id = {_p(conn)} AND released_at IS NULL",
        (now, session_id),
    )
    conn.commit()

    return _get_session(conn, session_id)

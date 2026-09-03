"""Session registration, heartbeat, and mode mutations."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_contracts.session_lane import UNRESOLVED_EXECUTION_LANE
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
from .session_model_columns import MODEL_COLUMNS, facts_values, merged_facts
from .sessions_lifecycle_identity import (
    existing_registration_row,
    normalize_observed_identity,
    refresh_active_duplicate_identity,
    resolve_reactivation_executor_version,
    resolve_reactivation_lane,
    resolve_session_actor_id,
    resolve_session_project_id,
)
from .sessions_lifecycle_reactivation import emit_reactivated_with_released_claims
from .sessions_started_event import session_started_context
from .sessions_reactivation_driver import (
    build_reactivation_driver_stamp,
    record_reactivation_wake_driver,
)
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
    model_facts: SessionModelFacts,
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
    operator-started session may register under a different value. Wake
    resolves against that column rather than assuming the two agree.
    """
    now = _now_iso()
    envelope_json = json.dumps(offer_envelope) if offer_envelope else None
    resolved_actor_id = resolve_session_actor_id(
        conn, actor_id, launch_id=launch_id
    )
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
        "provider, " + ", ".join(MODEL_COLUMNS) + ", execution_lane, workspace, "
        "mode, offered_at, last_heartbeat, ended_at, offer_envelope, actor_id, "
        "project_id"
    )
    # fmt: off
    insert_values: List[Any] = [
        session_id, canonical_executor, display_name, executor_version, machine_id,
        provider, *facts_values(model_facts), execution_lane, workspace, mode,
        now, now, None, envelope_json, resolved_actor_id, resolved_project_id,
    ]
    # fmt: on
    if has_thread_col:
        insert_cols += ", native_thread_id"
        insert_values.append(native_thread_id)
    if has_episode_col:
        insert_cols += ", episode_started_at"
        insert_values.append(now)
    insert_placeholders = ", ".join([p] * len(insert_values))
    # Populated only on the reactivation branch below; a fresh insert leaves
    # the event context untouched.
    reactivation_driver: Dict[str, Any] = {}
    # Reactivation folds the reading into what the row already proved.
    resolved_facts = model_facts

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
        if existing is None or existing["ended_at"] is None:
            refresh_active_duplicate_identity(
                conn,
                placeholder=p,
                existing=existing,
                session_id=session_id,
                model_facts=model_facts,
                execution_lane=execution_lane,
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
        resolved_lane = resolve_reactivation_lane(
            existing, execution_lane=execution_lane
        )
        driver_version = executor_version
        executor_version = resolve_reactivation_executor_version(
            existing, incoming_surface=display_name, incoming_version=driver_version
        )
        # An explicitly supplied or inherited-from-launch actor overwrites;
        # a resolved operating actor only fills a row that carries none, so a
        # session that registered under a named actor keeps it.
        actor_clause = (
            f", actor_id = {p}"
            if actor_id is not None or launch_id
            else f", actor_id = COALESCE(actor_id, {p})"
        )

        episode_clause = f", episode_started_at = {p}" if has_episode_col else ""
        thread_clause = (
            f", native_thread_id = COALESCE({p}, native_thread_id)"
            if has_thread_col
            else ""
        )
        model_assignments = ", ".join(f"{column} = {p}" for column in MODEL_COLUMNS)
        # fmt: off
        params: List[Any] = [
            provider, *facts_values(resolved_facts), resolved_lane, workspace, mode,
            envelope_json, executor_version, machine_id,
        ]
        # fmt: on
        if thread_clause:
            params.append(native_thread_id)
        if episode_clause:
            params.append(now)
        params.append(resolved_actor_id)
        project_clause = f", project_id = {p}"
        params.append(resolved_project_id)
        params.append(session_id)

        # Registration/reactivation is a probe, not session activity.
        cursor = conn.execute(
            f"""UPDATE harness_sessions
               SET provider = {p},
                   {model_assignments},
                   execution_lane = {p},
                   workspace = {p},
                   mode = {p},
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
        execution_lane = resolved_lane

    event_context = session_started_context(
        conn,
        placeholder=p,
        session_id=session_id,
        fallback_executor=canonical_executor,
        fallback_surface=display_name,
        provider=provider,
        model_facts=resolved_facts,
        execution_lane=execution_lane,
        workspace=workspace,
        mode=mode,
        executor_version=executor_version,
        machine_id=machine_id,
        project_id=resolved_project_id,
        entrypoint=entrypoint,
        reactivation_driver=reactivation_driver,
    )
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



"""Model/lane healing helpers for session registration."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from yoke_contracts.session_lane import lane_is_unresolved
from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.domain.session_model_columns import MODEL_COLUMNS, changed_columns


def resolve_session_actor_id(conn: Any, explicit: Optional[int]) -> int:
    """Bind the session's actor: the explicit one, else this universe's.

    An explicit actor (the verified bearer-token actor over https, or one
    an operator surface supplied) wins after a presence check; otherwise
    the universe's operating actor is resolved, because the identity a
    session acts for already exists by the time it registers. Nothing
    falls through to NULL: an actor-less session cannot register a path
    claim, and that refusal lands far from the registration that caused
    it, so registration refuses here with the reason and the recovery.

    Resolving the operating actor — and only that branch — is also where
    a single-owner universe converges the org admin role it operates
    under. Birth grants it, but an engine upgraded in place over a
    universe born before the grant existed never re-enters birth,
    leaving sessions bound and then denied on every mutation, and
    registration is the first moment the upgraded engine names that
    actor. An explicitly supplied actor is the bearer-token path, where
    a control plane establishes its administrators through token
    bootstrap and sign-in instead, so that branch converges nothing and
    a hosted registration never reaches the grant at all.
    """
    from yoke_core.domain.local_operating_actor import (
        converge_operating_actor_grant,
    )
    from yoke_core.domain.session_actor_binding import (
        explicit_actor_binding,
        resolve_operating_actor,
    )
    from yoke_core.domain.sessions import SessionError

    if explicit is not None:
        binding = explicit_actor_binding(conn, explicit)
    else:
        binding = resolve_operating_actor(conn)
        if binding.actor_id is not None:
            converge_operating_actor_grant(conn)
    if binding.actor_id is not None:
        return binding.actor_id
    raise SessionError(
        binding.code,
        f"Session registration cannot bind an actor: {binding.detail}",
    )


def resolve_session_project_id(conn: Any, explicit: int) -> int:
    """Require a positive project id that exists on this authority."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.sessions import SessionError

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
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        found = conn.execute(
            f"SELECT 1 FROM projects WHERE id = {marker}",
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


def normalize_observed_identity(
    executor_version: Optional[str],
    machine_id: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Validate bounded client-observed identity facts before persistence."""
    from yoke_core.domain.sessions import SessionError

    version = str(executor_version or "").strip() or None
    if version is not None and len(version) > 128:
        raise SessionError(
            "EXECUTOR_VERSION_INVALID",
            "Session executor_version must be at most 128 characters.",
        )
    machine = str(machine_id or "").strip() or None
    if machine is not None:
        try:
            parsed = str(uuid.UUID(machine))
        except (ValueError, TypeError, AttributeError):
            parsed = ""
        if parsed != machine:
            raise SessionError(
                "MACHINE_ID_INVALID",
                "Session machine_id must be a canonical UUID.",
            )
    return version, machine


def _stored_value(row: Any, key: str, default: str = "") -> str:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return value or default


def lane_should_upgrade(stored_lane: str, incoming_lane: str) -> bool:
    """True when an opt-out stored lane can heal to a real incoming lane."""
    return lane_is_unresolved(stored_lane) and not lane_is_unresolved(incoming_lane)


def resolve_reactivation_lane(existing: Any, *, execution_lane: str) -> str:
    """Return the lane a reactivating session should carry.

    An opt-out incoming lane yields to a real stored one; anything else
    the caller resolved wins.
    """
    stored_lane = _stored_value(existing, "execution_lane")
    if lane_is_unresolved(execution_lane) and not lane_is_unresolved(stored_lane):
        return stored_lane
    return execution_lane


def existing_registration_row(
    conn: Any,
    *,
    placeholder: str,
    session_id: str,
    include_native_thread: bool,
) -> Any:
    """Read the row a duplicate registration collided with."""
    thread_select = ", native_thread_id" if include_native_thread else ""
    return conn.execute(
        "SELECT ended_at, terminated_at, " + ", ".join(MODEL_COLUMNS) + ", "
        "actor_id, execution_lane, project_id, executor, executor_version, "
        f"machine_id, executor_surface{thread_select} "
        f"FROM harness_sessions WHERE session_id = {placeholder}",
        (session_id,),
    ).fetchone()


def resolve_reactivation_executor_version(
    existing: Any,
    *,
    incoming_surface: Optional[str],
    incoming_version: Optional[str],
) -> Optional[str]:
    """Keep ``executor_version`` paired with the stored surface.

    A re-registering process may refresh the version only when its resolved
    surface equals the stored surface. Cross-surface drivers (a CLI wake of a
    desktop session) leave the stored pair untouched.
    """
    stored_surface = _stored_value(existing, "executor_surface") or None
    stored_version = _stored_value(existing, "executor_version") or None
    incoming = (incoming_surface or "").strip() or None
    if incoming == stored_surface:
        return incoming_version or stored_version
    return stored_version


def refresh_active_duplicate_identity(
    conn: Any,
    *,
    placeholder: str,
    existing: Any,
    session_id: str,
    model_facts: SessionModelFacts,
    execution_lane: str,
    resolved_actor_id: int,
    executor_surface: Optional[str],
    executor_version: Optional[str],
    machine_id: Optional[str],
    native_thread_id: Optional[str] = None,
) -> None:
    """Upgrade mutable identity fields on an active duplicate registration.

    Duplicate registration still raises ``SESSION_EXISTS`` to preserve
    caller semantics; this helper only performs upgrade-only healing first.
    """
    if existing is None:
        return
    model_columns, model_values = changed_columns(existing, model_facts)
    if model_columns:
        assignments = ", ".join(f"{column} = {placeholder}" for column in model_columns)
        conn.execute(
            f"UPDATE harness_sessions SET {assignments} "
            f"WHERE session_id = {placeholder}",
            (*model_values, session_id),
        )
        conn.commit()

    stored_lane = _stored_value(existing, "execution_lane")
    if lane_should_upgrade(stored_lane, execution_lane):
        conn.execute(
            f"UPDATE harness_sessions SET execution_lane = {placeholder} "
            f"WHERE session_id = {placeholder}",
            (execution_lane, session_id),
        )
        conn.commit()

    # A row registered before actor binding existed (or by a path that
    # could not resolve one) heals on its next registration probe.
    if existing["actor_id"] is None:
        conn.execute(
            f"UPDATE harness_sessions SET actor_id = {placeholder} "
            f"WHERE session_id = {placeholder} AND actor_id IS NULL",
            (resolved_actor_id, session_id),
        )
        conn.commit()

    observed_updates = []
    observed_values = []
    stored_surface = _stored_value(existing, "executor_surface") or None
    incoming_surface = str(executor_surface or "").strip() or None
    if incoming_surface and stored_surface is None:
        observed_updates.append(f"executor_surface = {placeholder}")
        observed_values.append(incoming_surface)
        stored_surface = incoming_surface
    if (
        executor_version
        and not _stored_value(existing, "executor_version")
        and incoming_surface == stored_surface
    ):
        observed_updates.append(f"executor_version = {placeholder}")
        observed_values.append(executor_version)
    if machine_id and not _stored_value(existing, "machine_id"):
        observed_updates.append(f"machine_id = {placeholder}")
        observed_values.append(machine_id)
    if native_thread_id and not _stored_value(existing, "native_thread_id"):
        observed_updates.append(f"native_thread_id = {placeholder}")
        observed_values.append(native_thread_id)
    if observed_updates:
        conn.execute(
            "UPDATE harness_sessions SET "
            + ", ".join(observed_updates)
            + f" WHERE session_id = {placeholder}",
            (*observed_values, session_id),
        )
        conn.commit()


__all__ = [
    "existing_registration_row",
    "lane_should_upgrade",
    "normalize_observed_identity",
    "refresh_active_duplicate_identity",
    "resolve_session_actor_id",
    "resolve_session_project_id",
    "resolve_reactivation_executor_version",
    "resolve_reactivation_lane",
]

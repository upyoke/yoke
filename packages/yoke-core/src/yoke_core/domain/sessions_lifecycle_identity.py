"""Model/lane healing helpers for session registration."""

from __future__ import annotations

from typing import Any, Optional
import uuid

from yoke_contracts.session_lane import lane_is_unresolved


def resolve_session_actor_id(conn: Any, explicit: Optional[int]) -> Optional[int]:
    """Validate an explicitly observed actor for a session row."""
    if explicit is None:
        return None
    from yoke_core.domain import db_backend

    try:
        from yoke_core.domain.actors import validate_actor_id

        if validate_actor_id(conn, int(explicit)):
            return int(explicit)
    except db_backend.operational_error_types(conn) + (ValueError,):
        return None
    return None


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
            f"SELECT 1 FROM projects WHERE id = {marker}", (project_id,),
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
    executor_version: Optional[str], machine_id: Optional[str],
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
    value = row[key]
    return value or default


def lane_should_upgrade(stored_lane: str, incoming_lane: str) -> bool:
    """True when an opt-out stored lane can heal to a real incoming lane."""
    return lane_is_unresolved(stored_lane) and not lane_is_unresolved(incoming_lane)


def resolve_reactivation_identity(
    existing: Any,
    *,
    model: str,
    execution_lane: str,
) -> tuple[str, str]:
    """Return ``(model, lane)`` for reactivating an ended session."""
    from yoke_harness.hooks.identity import _is_placeholder_model

    stored_model = _stored_value(existing, "model")
    resolved_model = (
        stored_model
        if _is_placeholder_model(model) and not _is_placeholder_model(stored_model)
        else model
    )
    stored_lane = _stored_value(existing, "execution_lane")
    resolved_lane = (
        stored_lane
        if lane_is_unresolved(execution_lane) and not lane_is_unresolved(stored_lane)
        else execution_lane
    )
    return resolved_model, resolved_lane


def refresh_active_duplicate_identity(
    conn: Any,
    *,
    placeholder: str,
    existing: Any,
    session_id: str,
    model: str,
    execution_lane: str,
    actor_id: Optional[int],
    resolved_actor_id: Optional[int],
    executor_version: Optional[str],
    machine_id: Optional[str],
) -> None:
    """Upgrade mutable identity fields on an active duplicate registration.

    Duplicate registration still raises ``SESSION_EXISTS`` to preserve
    caller semantics; this helper only performs upgrade-only healing first.
    """
    if existing is None:
        return
    from yoke_harness.hooks.identity import _is_placeholder_model

    stored_model = _stored_value(existing, "model")
    if _is_placeholder_model(stored_model) and not _is_placeholder_model(model):
        conn.execute(
            f"UPDATE harness_sessions SET model = {placeholder} "
            f"WHERE session_id = {placeholder}",
            (model, session_id),
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

    if (
        actor_id is not None
        and resolved_actor_id is not None
        and existing["actor_id"] is None
    ):
        conn.execute(
            f"UPDATE harness_sessions SET actor_id = {placeholder} "
            f"WHERE session_id = {placeholder} AND actor_id IS NULL",
            (resolved_actor_id, session_id),
        )
        conn.commit()

    observed_updates = []
    observed_values = []
    if executor_version and not _stored_value(existing, "executor_version"):
        observed_updates.append(f"executor_version = {placeholder}")
        observed_values.append(executor_version)
    if machine_id and not _stored_value(existing, "machine_id"):
        observed_updates.append(f"machine_id = {placeholder}")
        observed_values.append(machine_id)
    if observed_updates:
        conn.execute(
            "UPDATE harness_sessions SET " + ", ".join(observed_updates)
            + f" WHERE session_id = {placeholder}",
            (*observed_values, session_id),
        )
        conn.commit()


__all__ = [
    "lane_should_upgrade",
    "normalize_observed_identity",
    "refresh_active_duplicate_identity",
    "resolve_session_actor_id",
    "resolve_session_project_id",
    "resolve_reactivation_identity",
]

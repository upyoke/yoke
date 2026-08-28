"""Write a launch's requested model onto a bound cursor session.

Cursor's wired hook payloads report a bare ``model`` (no effort tier).
The launch already knows the variant it asked Cursor to run, so a
launch-bound cursor session stores that requested value in the one
session model field. Non-cursor surfaces and sessions with no launch
keep the self-report.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.session_launch_store import marker
from yoke_core.domain.session_launch_types import LaunchRecord


def _is_cursor_surface(surface: Any) -> bool:
    value = str(surface or "").strip().lower()
    return value == "cursor" or value.startswith("cursor-")


def apply_cursor_launch_model(
    conn: Any,
    launch: LaunchRecord,
    session_id: str,
) -> str:
    """Store ``launch.requested_model`` on a cursor session. Return it or ``""``."""
    requested = str(launch.requested_model or "").strip()
    if not requested or not _is_cursor_surface(launch.selected_surface):
        return ""
    return _write_session_model(conn, session_id, requested)


def heal_cursor_session_model_from_launch(
    conn: Any,
    session_id: str,
    executor_surface: Any,
) -> str:
    """Heal an already-bound cursor session whose stored model lacks the tier."""
    if not _is_cursor_surface(executor_surface):
        return ""
    requested = _bound_cursor_requested_model(conn, session_id)
    if not requested:
        return ""
    return _write_session_model(conn, session_id, requested)


def _bound_cursor_requested_model(conn: Any, session_id: str) -> str:
    from yoke_core.domain import db_backend

    p = marker(conn)
    try:
        row = conn.execute(
            "SELECT requested_model FROM session_launches "
            f"WHERE (registered_session_id = {p} OR native_session_id = {p}) "
            "AND requested_model IS NOT NULL AND requested_model <> '' "
            "AND selected_surface LIKE 'cursor%' "
            "LIMIT 1",
            (session_id, session_id),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return ""
    if row is None:
        return ""
    value = row["requested_model"] if hasattr(row, "keys") else row[0]
    return str(value or "").strip()


def _write_session_model(conn: Any, session_id: str, model: str) -> str:
    p = marker(conn)
    conn.execute(
        f"UPDATE harness_sessions SET model = {p} WHERE session_id = {p}",
        (model, session_id),
    )
    return model


__all__ = [
    "apply_cursor_launch_model",
    "heal_cursor_session_model_from_launch",
]

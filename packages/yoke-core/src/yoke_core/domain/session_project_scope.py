"""Canonical session-project scope resolver.

Argless ``/yoke charge`` still compute the all-projects
schedule by default so other projects stay visible for the elsewhere
reply. ``--project yoke,example-project`` narrows that compute scope and
bypasses the workspace-home assignment filter. Assignment itself is
filtered to the session workspace project in
``session_workspace_frontier`` — this module only resolves compute scope.
"""

from __future__ import annotations
from yoke_core.domain.project_retirement import active_projects_where

from typing import Any, List, Optional, Union

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project, row_value


def resolve_session_project_scope(
    conn: Any,
    *,
    override: Optional[List[Union[str, int]]] = None,
) -> List[int]:
    """Return the project ids in scope for this session.

    - `override` non-empty → resolve each slug or numeric id against
      ``projects`` and return canonical numeric ids.
    - Otherwise → return every registered project id (all-projects default).

    Unknown overrides raise ``ValueError`` naming the unknown value and the
    registered set. An empty list or ``None`` override is treated as no
    override (returns the all-projects default).
    """
    registered = _list_registered_project_ids(conn)
    if not override:
        return registered

    resolved: List[int] = []
    for project in override:
        try:
            ident = resolve_project(conn, project, required=True)
        except LookupError as exc:
            known = ", ".join(_list_registered_project_refs(conn))
            raise ValueError(
                f"Unknown project {project!r} in --project override. "
                f"Registered projects: {known or '(none)'}."
            ) from exc
        except db_backend.operational_error_types(conn) as exc:
            _refuse_unavailable_roster(conn, exc)
        assert ident is not None
        resolved.append(int(ident.id))
    return resolved


def parse_project_cli_arg(arg: Optional[str]) -> Optional[List[str]]:
    """Parse a ``--project`` CLI value into a list of project refs.

    - ``None``, empty, or whitespace-only input returns ``None`` (no override).
    - Whitespace around each comma-separated slug/id is stripped.
    - Empty segments (e.g. trailing commas) are dropped.
    - A non-empty result is always a list of cleaned refs.
    """
    if arg is None:
        return None
    pieces = [piece.strip() for piece in arg.split(",")]
    cleaned = [piece for piece in pieces if piece]
    if not cleaned:
        return None
    return cleaned


def _list_registered_project_ids(conn: Any) -> List[int]:
    """Return the actual registry; missing authority never invents a project."""
    try:
        rows = conn.execute(
            "SELECT id FROM projects" + active_projects_where(conn) + " ORDER BY id"
        ).fetchall()
    except db_backend.operational_error_types(conn) as exc:
        _refuse_unavailable_roster(conn, exc)
    return [int(row_value(row, "id", 0)) for row in rows]


def _list_registered_project_refs(conn: Any) -> List[str]:
    try:
        rows = conn.execute(
            "SELECT id, slug FROM projects"
            + active_projects_where(conn)
            + " ORDER BY id"
        ).fetchall()
    except db_backend.operational_error_types(conn) as exc:
        _refuse_unavailable_roster(conn, exc)
    return [f"{row_value(row, 'id', 0)}/{row_value(row, 'slug', 1)}" for row in rows]


def _refuse_unavailable_roster(conn: Any, exc: Exception) -> None:
    if db_backend.connection_is_postgres(conn):
        conn.rollback()
    raise ValueError(
        "project_roster_unavailable: registered projects could not be read. "
        "Restore the selected authority and run `yoke projects list`; no project was inferred."
    ) from exc


__all__ = ["resolve_session_project_scope", "parse_project_cli_arg"]

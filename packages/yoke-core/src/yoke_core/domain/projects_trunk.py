"""Resolve the trunk branch for a Yoke project.

The trunk is read from ``projects.default_branch`` with a fallback to
``"main"`` when the column value is missing, NULL, or blank. The
path-claim registration on-ramp uses the trunk as the integration
target when the CLI caller omits ``--integration-target``, so the
no-flag call does the right thing for the 95%+ case and stops agents
from improvising self-referencing slug values when an earlier
``required=True`` usage error nudged them off the happy path.

Reading the project row is cheap; callers do not memoize. Tests and
in-memory fixtures that omit the projects row use
:func:`resolve_trunk_safe`, which returns ``None`` instead of raising
so the validator can fall through to the package default without
forcing every fixture to seed a row.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend


DEFAULT_TRUNK = "main"


class ProjectNotFound(Exception):
    """Raised when ``project_id`` has no row in the ``projects`` table."""


def _row_value(row, column: str):
    if row is None:
        return None
    if hasattr(row, "keys"):
        return row[column]
    return row[0]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_trunk(conn: Any, project_id: int) -> str:
    """Return the trunk branch name for ``project_id``.

    Reads ``projects.default_branch`` and returns ``"main"`` when the
    row exists but the column is NULL or whitespace-only. Raises
    :class:`ProjectNotFound` when ``project_id`` has no projects row,
    or when the ``projects`` table itself does not exist (the row is
    indistinguishable from "missing" to callers that only need the
    trunk hint) — callers that want the silent path use
    :func:`resolve_trunk_safe`.
    """
    try:
        p = _p(conn)
        row = conn.execute(
            f"SELECT default_branch FROM projects WHERE id = {p}",
            (project_id,),
        ).fetchone()
    except db_backend.operational_error_types(conn) as exc:
        raise ProjectNotFound(
            f"projects lookup unavailable for {project_id!r}: {exc}"
        ) from exc
    if row is None:
        raise ProjectNotFound(
            f"project {project_id!r} has no row in projects",
        )
    raw = _row_value(row, "default_branch")
    if raw is None:
        return DEFAULT_TRUNK
    value = str(raw).strip()
    if not value:
        return DEFAULT_TRUNK
    return value


def resolve_trunk_safe(
    conn: Any, project_id: int,
) -> Optional[str]:
    """Best-effort trunk lookup.

    Returns the same string :func:`resolve_trunk` would return, or
    ``None`` when ``project_id`` has no projects row. Callers that
    only need the trunk as a hint (for the unresolvable-target error
    message) use this form so a missing projects fixture does not
    explode the validator path.
    """
    try:
        return resolve_trunk(conn, project_id)
    except ProjectNotFound:
        return None


__all__ = [
    "DEFAULT_TRUNK",
    "ProjectNotFound",
    "resolve_trunk",
    "resolve_trunk_safe",
]

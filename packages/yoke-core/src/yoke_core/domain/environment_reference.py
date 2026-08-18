"""One resolver for every surface that names a deployment environment.

An environment is named by its registered name within a project. Callers pass
that name; nothing outside this module needs to know a row id. Resolution is
project-scoped because names repeat across projects — every project has a
``prod`` — and it refuses rather than guesses, naming the project's registered
environments so the caller can see what was available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_core.domain import db_backend


class EnvironmentReferenceError(LookupError):
    """A named environment does not resolve within its project."""


@dataclass(frozen=True)
class EnvironmentReference:
    """One resolved environment row, addressed by name within a project."""

    id: Any
    name: str
    site: Any
    project_id: int


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_value(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def registered_names(conn: Any, *, project_id: int) -> list[str]:
    """Every environment name registered in one project, sorted."""
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT e.name FROM environments e JOIN sites s ON s.id = e.site "
        f"WHERE s.project_id = {marker} ORDER BY e.name",
        (int(project_id),),
    ).fetchall()
    return [str(_row_value(row, "name", 0)) for row in rows]


def resolve(conn: Any, *, project_id: int, name: str) -> EnvironmentReference:
    """Resolve one registered environment name within one project.

    Raises :class:`EnvironmentReferenceError` when the name is absent, naming
    the project's registered environments. A name that resolves to more than
    one row is also a refusal: the caller asked for one environment and the
    project cannot say which, which is the condition the per-project name
    uniqueness rule exists to prevent.
    """
    needle = str(name or "").strip()
    if not needle:
        raise EnvironmentReferenceError(
            "an environment name is required; "
            f"project {project_id} registers {_render(registered_names(conn, project_id=project_id))}"
        )
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT e.id, e.name, e.site, s.project_id "
        "FROM environments e JOIN sites s ON s.id = e.site "
        f"WHERE s.project_id = {marker} AND e.name = {marker}",
        (int(project_id), needle),
    ).fetchall()
    if not rows:
        raise EnvironmentReferenceError(
            f"environment {needle!r} is not registered in project {project_id}; "
            f"registered: {_render(registered_names(conn, project_id=project_id))}"
        )
    if len(rows) > 1:
        raise EnvironmentReferenceError(
            f"environment name {needle!r} resolves to {len(rows)} rows in "
            f"project {project_id}; a name identifies one environment per project"
        )
    row = rows[0]
    return EnvironmentReference(
        id=_row_value(row, "id", 0),
        name=str(_row_value(row, "name", 1)),
        site=_row_value(row, "site", 2),
        project_id=int(_row_value(row, "project_id", 3)),
    )


def _render(names: list[str]) -> str:
    return ", ".join(names) if names else "(none)"


__all__ = [
    "EnvironmentReference",
    "EnvironmentReferenceError",
    "registered_names",
    "resolve",
]

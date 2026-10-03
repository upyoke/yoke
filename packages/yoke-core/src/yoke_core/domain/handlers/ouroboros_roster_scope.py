"""Resolve explicit observation-roster projects within actor visibility."""

from yoke_core.domain.handlers.items_project_scope import (
    actor_visible_scope,
    resolve_visible_project_ids,
)
from yoke_core.domain.ouroboros_entry_roster import RosterFilterError


def roster_project_ids(conn, request):
    payload = request.payload or {}
    project, projects = payload.get("project"), payload.get("projects")
    if projects is not None and (
        not isinstance(projects, list)
        or not all(isinstance(value, str) for value in projects)
    ):
        raise RosterFilterError(
            "projects must be a list of project references", "$.payload.projects"
        )
    if projects is not None and project:
        raise RosterFilterError(
            "Use project or projects, not both", "$.payload.projects"
        )
    references = (
        projects if projects is not None else [str(project)] if project else None
    )
    if references is None:
        raise RosterFilterError(
            "project or projects is required for roster reads", "$.payload.project"
        )
    ids = resolve_visible_project_ids(
        conn, references, actor_visible_scope(conn, request)
    )
    if projects is None and not ids:
        raise RosterFilterError("Unknown or unavailable project", "$.payload.project")
    return ids

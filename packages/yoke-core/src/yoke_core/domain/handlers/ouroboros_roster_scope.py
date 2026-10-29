"""Feedback visibility, scope parsing and project/NULL SQL predicates."""

from yoke_core.domain.handlers.items_project_scope import actor_visible_scope, resolve_visible_project_ids
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.project_identity import placeholder
from yoke_core.domain.actor_project_visibility import numeric_actor_id


def includes_unscoped(conn, request):
    actor = numeric_actor_id(request.actor.actor_id if request.actor else None)
    if actor is None:
        return True  # Local universe owner.
    from yoke_core.domain.actor_state import actor_is_active
    if not actor_is_active(conn, actor):
        return False
    return query_one(conn,
        "SELECT 1 FROM actor_org_roles a JOIN roles r ON r.id=a.role_id "
        f"WHERE a.actor_id={placeholder(conn)} AND r.name='admin' LIMIT 1", (actor,)) is not None


def roster_project_ids(conn, request):
    from yoke_core.domain.ouroboros_entry_roster import RosterFilterError
    payload = request.payload or {}
    scope = payload.get("scope", "universe")
    if scope not in ("universe", "project", "unscoped"):
        raise RosterFilterError("feedback_scope_invalid: use universe, project or unscoped", "$.payload.scope")
    visible = actor_visible_scope(conn, request)
    unscoped = includes_unscoped(conn, request) and scope != "project"
    if scope == "unscoped":
        return [], unscoped
    if scope == "universe":
        ids = sorted(visible) if visible is not None else [int(row[0]) for row in conn.execute("SELECT id FROM projects").fetchall()]
        return ids, unscoped
    project, projects = payload.get("project"), payload.get("projects")
    if projects is not None and (not isinstance(projects, list) or not all(isinstance(value, str) for value in projects)):
        raise RosterFilterError("projects must be a list of project references", "$.payload.projects")
    if projects is not None and project:
        raise RosterFilterError("Use project or projects, not both", "$.payload.projects")
    references = projects if projects is not None else [str(project)] if project else None
    if references is None:
        raise RosterFilterError("feedback_project_required: pass --project P for project scope", "$.payload.project")
    return resolve_visible_project_ids(conn, references, visible) or [], False


def scope_predicate(conn, project_ids, include_unscoped=False):
    ids = list(project_ids or [])
    clause = f"o.project_id IN ({','.join([placeholder(conn)] * len(ids))})" if ids else "1=0"
    if include_unscoped:
        clause = f"({clause} OR o.project_id IS NULL)"
    return clause, ids


def entry_visible(conn, request, entry):
    if not entry.get("project"):
        return includes_unscoped(conn, request)
    visible = actor_visible_scope(conn, request)
    return bool(resolve_visible_project_ids(conn, [entry["project"]], visible))

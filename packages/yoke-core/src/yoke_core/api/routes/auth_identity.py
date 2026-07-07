"""Authenticated identity summary for product onboarding."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.api.http_auth import require_auth_context
from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids

router = APIRouter()


@router.get("/auth/identity")
def get_auth_identity(request: Request) -> JSONResponse:
    """Return non-secret token actor, org, and visible-project evidence."""
    auth = require_auth_context(request)
    with db_helpers.connect() as conn:
        body = _identity_payload(conn, auth)
    return JSONResponse(content=body)


def _identity_payload(conn: Any, auth: Any) -> dict[str, Any]:
    orgs = _org_roles(conn, auth.actor_id)
    org_roles_by_id = {int(org["id"]): tuple(org["roles"]) for org in orgs}
    projects = _visible_projects(conn, auth.actor_id, org_roles_by_id)
    return {
        "checked": True,
        "ok": True,
        "status": "verified",
        "source": "identity",
        "token": {"id": auth.token_id, "name": auth.token_name},
        "actor": _actor_summary(conn, auth.actor_id),
        "orgs": orgs,
        "projects": projects,
    }


def _actor_summary(conn: Any, actor_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT kind, system_component FROM actors WHERE id = {p}",
        (actor_id,),
    ).fetchone()
    labels = conn.execute(
        f"SELECT surface, label FROM actor_labels WHERE actor_id = {p} "
        "ORDER BY surface",
        (actor_id,),
    ).fetchall()
    label = ""
    for surface, value in labels:
        if str(surface) == "github_label":
            label = str(value)
            break
    if not label and labels:
        label = str(labels[0][1])
    return {
        "id": actor_id,
        "kind": str(row[0]) if row else "",
        "label": label,
        "system_component": str(row[1]) if row and row[1] is not None else None,
    }


def _org_roles(conn: Any, actor_id: int) -> list[dict[str, Any]]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT o.id, o.slug, o.name, r.name "
        "FROM actor_org_roles aor "
        "JOIN organizations o ON o.id = aor.org_id "
        "JOIN roles r ON r.id = aor.role_id "
        f"WHERE aor.actor_id = {p} "
        "ORDER BY o.slug, r.name",
        (actor_id,),
    ).fetchall()
    by_org: dict[int, dict[str, Any]] = {}
    for org_id, slug, name, role in rows:
        key = int(org_id)
        entry = by_org.setdefault(
            key,
            {
                "id": key,
                "slug": str(slug),
                "name": str(name),
                "roles": [],
            },
        )
        entry["roles"].append(str(role))
    return list(by_org.values())


def _visible_projects(
    conn: Any,
    actor_id: int,
    org_roles_by_id: dict[int, tuple[str, ...]],
) -> list[dict[str, Any]]:
    visible_ids = actor_visible_project_ids(conn, actor_id) or set()
    if not visible_ids:
        return []
    p = _p(conn)
    placeholders = ",".join(p for _ in visible_ids)
    rows = conn.execute(
        "SELECT pr.id, pr.slug, pr.name, pr.org_id, o.slug, o.name "
        "FROM projects pr "
        "LEFT JOIN organizations o ON o.id = pr.org_id "
        f"WHERE pr.id IN ({placeholders}) "
        "ORDER BY pr.slug",
        tuple(sorted(visible_ids)),
    ).fetchall()
    direct_roles = _project_roles(conn, actor_id)
    projects: list[dict[str, Any]] = []
    for project_id, slug, name, org_id, org_slug, org_name in rows:
        numeric_project_id = int(project_id)
        numeric_org_id = int(org_id) if org_id is not None else None
        org_roles = org_roles_by_id.get(numeric_org_id or 0, ())
        roles = sorted(set(org_roles) | set(direct_roles.get(numeric_project_id, ())))
        projects.append({
            "id": numeric_project_id,
            "slug": str(slug),
            "name": str(name),
            "org": {
                "id": numeric_org_id,
                "slug": str(org_slug) if org_slug is not None else "",
                "name": str(org_name) if org_name is not None else "",
            },
            "roles": roles,
            "direct_roles": list(direct_roles.get(numeric_project_id, ())),
            "org_roles": list(org_roles),
        })
    return projects


def _project_roles(conn: Any, actor_id: int) -> dict[int, tuple[str, ...]]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT apr.project_id, r.name "
        "FROM actor_project_roles apr "
        "JOIN roles r ON r.id = apr.role_id "
        f"WHERE apr.actor_id = {p} "
        "ORDER BY apr.project_id, r.name",
        (actor_id,),
    ).fetchall()
    grouped: dict[int, list[str]] = {}
    for project_id, role in rows:
        grouped.setdefault(int(project_id), []).append(str(role))
    return {project_id: tuple(roles) for project_id, roles in grouped.items()}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


__all__ = ["router"]

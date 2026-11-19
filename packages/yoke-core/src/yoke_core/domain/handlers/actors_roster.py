"""Read-only roster for the Team page.

An org owner or admin sees every actor and grant. Anyone else sees grants
only on projects they can see, and no actor whose only access is to
projects hidden from them, so a project-only person never learns of a
project they were not given.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.profile_read import read_identity, read_roles
from yoke_core.domain.profile_read import read_tokens
from yoke_core.domain.actor_state import actor_status_sql
from yoke_core.domain.actor_permissions import (
    PERM_ORG_ADMIN,
    ROLE_DESCRIPTIONS,
    PermissionDenied,
)
from yoke_core.domain.actor_role import (
    BOOTSTRAP_ONLY_ROLES,
    HUMAN_ORG_ROLES,
    MACHINE_ONLY_ROLES,
)
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.control_plane_authority import require_control_plane_permission


class ActorsRosterRequest(BaseModel):
    pass


class ActorsRosterResponse(BaseModel):
    rows: List[Dict[str, Any]]
    current_actor_id: Optional[int]
    can_manage_actors: bool
    person_org_roles: List[str]
    role_descriptions: Dict[str, str]
    machine_only_roles: List[str]
    bootstrap_only_roles: List[str]
    projects: List[Dict[str, str]]


def _visible_rows(
    rows: List[Dict[str, Any]], slugs: set, current_actor_id: Optional[int]
) -> List[Dict[str, Any]]:
    """Drop grants on hidden projects, then actors left with no visible access."""
    kept = []
    for row in rows:
        grants = row["roles"]["projects"]
        shown = [grant for grant in grants if grant["project"] in slugs]
        if grants and not shown and not row["roles"]["org"]:
            if row["id"] != current_actor_id:
                continue
        row["roles"]["projects"] = shown
        kept.append(row)
    return kept


def handle_actors_roster(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="actors.roster requires target.kind='global'; retry without a project target",
                jsonpath="$.target.kind",
            ),
        )

    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        status = actor_status_sql(conn, "a")
        actors = conn.execute(
            f"SELECT a.id, a.kind, a.name, a.system_component, {status} "
            "FROM actors a ORDER BY a.id"
        ).fetchall()
        rows = []
        for actor_id, kind, name, system_component, status in actors:
            actor_id = int(actor_id)
            rows.append(
                {
                    "id": actor_id,
                    "kind": kind,
                    "name": name or system_component or f"actor {actor_id}",
                    "status": status,
                    "roles": read_roles(conn, actor_id),
                    "identity": read_identity(conn, actor_id),
                    "tokens": read_tokens(conn, actor_id),
                }
            )
        raw_actor_id = (request.actor.actor_id or "").strip()
        current_actor_id = int(raw_actor_id) if raw_actor_id.isdigit() else None
        can_manage_actors = False
        if current_actor_id is not None:
            try:
                require_control_plane_permission(
                    conn,
                    actor_id=current_actor_id,
                    permission_key=PERM_ORG_ADMIN,
                )
                can_manage_actors = True
            except PermissionDenied:
                pass
        visible = (
            None
            if can_manage_actors
            else actor_visible_project_ids(conn, current_actor_id)
        )
        projects = [
            {"slug": str(slug), "name": str(name or slug)}
            for project_id, slug, name in conn.execute(
                "SELECT id, slug, name FROM projects ORDER BY slug"
            ).fetchall()
            if visible is None or int(project_id) in visible
        ]
        if visible is not None:
            rows = _visible_rows(rows, {p["slug"] for p in projects}, current_actor_id)
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "rows": rows,
            "current_actor_id": current_actor_id,
            "can_manage_actors": can_manage_actors,
            "person_org_roles": list(HUMAN_ORG_ROLES),
            "role_descriptions": dict(ROLE_DESCRIPTIONS),
            "machine_only_roles": list(MACHINE_ONLY_ROLES),
            "bootstrap_only_roles": list(BOOTSTRAP_ONLY_ROLES),
            "projects": projects,
        },
        primary_success=True,
    )

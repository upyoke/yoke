"""A project-only person sees only their project, everywhere they look."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api.routes.auth_identity import _visible_projects
from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    grant_actor_org_role,
    permission_decision,
    seed_roles_and_permissions,
)
from yoke_core.domain.actor_project_role import set_actor_project_role
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id
from yoke_core.domain.handlers.actors_roster import handle_actors_roster
from yoke_core.domain.handlers.projects_get import handle_projects_list


def _request(function, actor_id):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload={},
    )


def _universe(conn):
    """Org with projects yoke and hidden; a project-only viewer and a hidden-only member."""
    seed_roles_and_permissions(conn)
    org_id = resolve_control_plane_org_id(conn)
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at, org_id) "
        "VALUES (88, 'hidden', 'Hidden', 'HID', '2026-10-04', %s)",
        (org_id,),
    )
    conn.execute("UPDATE projects SET org_id = %s WHERE slug = 'yoke'", (org_id,))
    conn.commit()
    admin = seed_human_actor(conn, "Admin")
    grant_actor_org_role(conn, actor_id=admin, org_id=org_id, role_name="admin")
    viewer = seed_human_actor(conn, "Project Viewer")
    outsider = seed_human_actor(conn, "Hidden Only")
    for actor, project in ((viewer, "yoke"), (viewer, "hidden"), (outsider, "hidden")):
        set_actor_project_role(
            conn, actor_id=actor, project=project, role="viewer", caller_actor_id=admin
        )
    conn.execute(
        "DELETE FROM actor_project_roles WHERE actor_id = %s AND project_id = 88",
        (viewer,),
    )
    conn.commit()
    return admin, viewer, outsider


def test_project_only_person_sees_and_reads_only_their_project(test_db):
    _admin, viewer, _outsider = _universe(test_db)

    listed = handle_projects_list(_request("projects.list", viewer))
    assert listed.primary_success, listed.error
    assert [row["slug"] for row in listed.result_payload["rows"]] == ["yoke"]
    assert [row["slug"] for row in _visible_projects(test_db, viewer, {})] == ["yoke"]
    yoke_id = int(test_db.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()[0])
    assert permission_decision(
        test_db, actor_id=viewer, project_id=yoke_id, permission_key=PERM_ITEMS_READ
    ).allowed
    assert not permission_decision(
        test_db, actor_id=viewer, project_id=88, permission_key=PERM_ITEMS_READ
    ).allowed


def test_roster_hides_grants_and_people_on_projects_the_caller_cannot_see(test_db):
    admin, viewer, outsider = _universe(test_db)

    seen = handle_actors_roster(_request("actors.roster", viewer)).result_payload
    ids = {row["id"] for row in seen["rows"]}
    assert viewer in ids and admin in ids and outsider not in ids
    grants = [g for row in seen["rows"] for g in row["roles"]["projects"]]
    assert {g["project"] for g in grants} == {"yoke"}
    assert [p["slug"] for p in seen["projects"]] == ["yoke"]
    assert seen["can_manage_actors"] is False

    full = handle_actors_roster(_request("actors.roster", admin)).result_payload
    outsider_row = next(row for row in full["rows"] if row["id"] == outsider)
    assert outsider_row["roles"]["projects"][0]["project"] == "hidden"
    assert {p["slug"] for p in full["projects"]} >= {"yoke", "hidden"}
    assert full["person_org_roles"] and "rows" in full

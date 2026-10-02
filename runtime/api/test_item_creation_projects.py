"""The creation dropdown offers writable projects, not every visible project."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.actor_permissions import (
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.handlers.projects_get import handle_projects_list


def test_creation_roster_excludes_viewer_projects(test_db):
    seed_roles_and_permissions(test_db)
    actor_id = seed_human_actor(test_db, name="Creation operator")
    projects = test_db.execute("SELECT id FROM projects ORDER BY id LIMIT 2").fetchall()
    writable, readonly = (int(row[0]) for row in projects)
    for project_id, role in [(writable, "operator"), (readonly, "viewer")]:
        grant_actor_project_role(
            test_db, actor_id=actor_id, project_id=project_id, role_name=role
        )
    request = FunctionCallRequest(
        function="projects.list",
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        payload={"fields": ["id", "slug"], "for_item_creation": True},
    )
    result = handle_projects_list(request)
    assert result.primary_success, result.error
    assert result.result_payload["creation_scoped"]
    assert [row["id"] for row in result.result_payload["rows"]] == [writable]


def test_creation_roster_requires_bound_actor(test_db):
    result = handle_projects_list(
        FunctionCallRequest(
            function="projects.list",
            target=TargetRef(kind="global"),
            actor=ActorContext(actor_id="", session_id=""),
            payload={"fields": ["id"], "for_item_creation": True},
        )
    )
    assert result.primary_success
    assert result.result_payload["rows"] == []

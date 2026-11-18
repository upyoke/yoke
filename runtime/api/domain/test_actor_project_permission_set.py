"""Permitted project sets answer exactly what per-project decisions answer."""

from runtime.api.fixtures.actor_roles import seed_org_role, seed_project_role
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.actor_permissions import (
    PERMISSION_DESCRIPTIONS,
    ROLE_PERMISSION_KEYS,
    permission_decision,
)
from yoke_core.domain.actor_project_visibility import actor_project_ids_with_permission
from yoke_core.domain.actors import seed_system_actor


def _second_org_project(conn):
    org = conn.execute(
        "INSERT INTO organizations(slug,name,created_at) "
        "VALUES ('other-org','Other org',now()) "
        "RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix,org_id,created_at) "
        "SELECT MAX(id)+1,'other-permissions','Other','OTH',%s,now() FROM projects",
        (org,),
    )
    conn.commit()


def _actors(conn):
    projects = [
        (int(row[0]), int(row[1]))
        for row in conn.execute(
            "SELECT id, org_id FROM projects WHERE org_id IS NOT NULL ORDER BY id"
        ).fetchall()
    ]
    actors = []
    for role in ROLE_PERMISSION_KEYS:
        org_actor = seed_system_actor(conn, f"permission-set-org-{role}")
        seed_org_role(conn, actor_id=org_actor, org_id=projects[0][1], role_name=role)
        project_actor = seed_system_actor(conn, f"permission-set-project-{role}")
        seed_project_role(
            conn, actor_id=project_actor, project_id=projects[-1][0], role_name=role
        )
        actors.extend((org_actor, project_actor))
    actors.append(seed_system_actor(conn, "permission-set-none"))
    return actors


def test_permitted_project_set_matches_each_decision(test_db):
    _second_org_project(test_db)
    actors = _actors(test_db)
    project_ids = [
        int(row[0])
        for row in test_db.execute("SELECT id FROM projects ORDER BY id").fetchall()
    ]
    assert len(project_ids) >= 2
    granted = 0
    for actor_id in actors:
        for key in PERMISSION_DESCRIPTIONS:
            expected = {
                project_id
                for project_id in project_ids
                if permission_decision(
                    test_db, actor_id=actor_id, project_id=project_id,
                    permission_key=key,
                ).allowed
            }
            granted += len(expected)
            counted = CountingConnection(test_db)
            assert (
                actor_project_ids_with_permission(counted, actor_id, key) == expected
            ), (actor_id, key)
            assert counted.count <= 2  # Active check plus one grant read.
    assert granted  # The matrix exercised real grants, not only denials.

"""A person's one role on one project, and removing a person's org role."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actor_project_role import project_roles_of
from yoke_core.domain.actor_role import org_roles_of
from yoke_core.domain.actors import seed_human_actor, seed_system_actor
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id
from yoke_core.domain.handlers.actor_project_role import (
    handle_actor_project_role_remove,
    handle_actor_project_role_set,
)
from yoke_core.domain.handlers.actor_role import handle_actor_role_remove


def _org(conn):
    seed_roles_and_permissions(conn)
    return resolve_control_plane_org_id(conn)


def _person(conn, name, role, org_id):
    actor_id = seed_human_actor(conn, name)
    grant_actor_org_role(conn, actor_id=actor_id, org_id=org_id, role_name=role)
    return actor_id


def _call(handler, function, caller, **payload):
    return handler(
        FunctionCallRequest(
            function=function,
            actor=ActorContext(actor_id=str(caller), session_id=""),
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


def _set(caller, **payload):
    return _call(handle_actor_project_role_set, "actors.project_role.set", caller, **payload)


def _remove(caller, **payload):
    return _call(
        handle_actor_project_role_remove, "actors.project_role.remove", caller, **payload
    )


def _role_remove(caller, **payload):
    return _call(handle_actor_role_remove, "actors.role.remove", caller, **payload)


def _yoke(conn):
    return int(conn.execute("SELECT id FROM projects WHERE slug = 'yoke'").fetchone()[0])


def test_set_makes_one_role_per_project_and_replaces_it(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = seed_human_actor(test_db, "Member")
    project_id = _yoke(test_db)

    first = _set(admin, actor_id=member, project="yoke", role="viewer")
    assert first.primary_success, first.error
    assert first.result_payload == {
        "actor_id": member,
        "project": "yoke",
        "role": "viewer",
        "previous_roles": [],
        "changed": True,
    }
    second = _set(admin, actor_id=member, project="yoke", role="operator")
    assert second.result_payload["previous_roles"] == ["viewer"]
    assert project_roles_of(test_db, member, project_id) == ["operator"]
    again = _set(admin, actor_id=member, project="yoke", role="operator")
    assert again.result_payload["changed"] is False
    # The lower-level grant path replaces too: never two roles on one project.
    grant_actor_project_role(
        test_db, actor_id=member, project_id=project_id, role_name="viewer",
        granted_by_actor_id=admin,
    )
    assert project_roles_of(test_db, member, project_id) == ["viewer"]


def test_remove_takes_every_role_on_the_project_and_repeats_safely(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = seed_human_actor(test_db, "Member")
    project_id = _yoke(test_db)
    test_db.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id, granted_at) "
        "SELECT %s, %s, id, '2026-01-01T00:00:00Z' FROM roles "
        "WHERE name IN ('viewer', 'operator')",
        (member, project_id),
    )
    test_db.commit()

    removed = _remove(admin, actor_id=member, project="yoke")
    assert removed.primary_success, removed.error
    assert removed.result_payload == {
        "actor_id": member,
        "project": "yoke",
        "previous_roles": ["operator", "viewer"],
        "changed": True,
    }
    assert project_roles_of(test_db, member, project_id) == []
    repeat = _remove(admin, actor_id=member, project="yoke")
    assert repeat.primary_success and repeat.result_payload["changed"] is False


@pytest.mark.parametrize(
    ("role", "code"),
    [
        ("deployment_ci", "machine_only_role"),
        ("member", "role_not_assignable"),
        ("owner", "owner_protected"),
    ],
)
def test_project_roles_a_person_cannot_hold_are_refused(test_db, role, code):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = seed_human_actor(test_db, "Member")

    refused = _set(admin, actor_id=member, project="yoke", role=role)

    assert refused.error.code == code
    assert project_roles_of(test_db, member, _yoke(test_db)) == []


def test_system_actors_unknown_projects_and_non_admins_are_refused(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    operator = _person(test_db, "Operator", "operator", org_id)
    system = seed_system_actor(test_db, "deploy-ci")

    assert (
        _set(admin, actor_id=system, project="yoke", role="viewer").error.code
        == "actor_not_human"
    )
    missing = _set(admin, actor_id=operator, project="nope", role="viewer")
    assert missing.error.code == "project_not_found"
    assert "yoke projects list" in missing.error.message
    assert (
        _set(operator, actor_id=admin, project="yoke", role="viewer").error.code
        == "permission_denied"
    )
    assert _remove(admin, actor_id=operator).error.code == "payload_invalid"
    assert _role_remove(admin, actor_id=system).error.code == "actor_not_human"


def test_owner_protection_guards_project_and_org_removal(test_db):
    org_id = _org(test_db)
    test_db.execute("DELETE FROM actor_org_roles WHERE org_id=%s", (org_id,))
    owner = seed_human_actor(test_db, "Owner")
    test_db.execute(
        "INSERT INTO actor_org_roles (actor_id,org_id,role_id,granted_at) "
        "SELECT %s,%s,id,CURRENT_TIMESTAMP FROM roles WHERE name='owner'",
        (owner, org_id),
    )
    test_db.commit()
    admin = _person(test_db, "Admin", "admin", org_id)

    assert _role_remove(admin, actor_id=owner).error.code == "owner_protected"
    assert (
        _set(admin, actor_id=owner, project="yoke", role="viewer").error.code
        == "owner_protected"
    )
    last = _role_remove(owner, actor_id=owner)
    assert last.error.code == "last_owner"
    assert org_roles_of(test_db, owner, org_id) == ["owner"]


def test_role_remove_leaves_only_project_roles(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = _person(test_db, "Member", "operator", org_id)
    assert _set(admin, actor_id=member, project="yoke", role="viewer").primary_success

    removed = _role_remove(admin, actor_id=member)

    assert removed.primary_success, removed.error
    assert removed.result_payload == {
        "actor_id": member,
        "previous_roles": ["operator"],
        "changed": True,
    }
    assert org_roles_of(test_db, member, org_id) == []
    assert project_roles_of(test_db, member, _yoke(test_db)) == ["viewer"]
    repeat = _role_remove(admin, actor_id=member)
    assert repeat.primary_success and repeat.result_payload["changed"] is False

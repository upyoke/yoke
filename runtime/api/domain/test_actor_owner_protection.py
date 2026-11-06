"""Owner boundaries hold for org/project grants, actor state and bootstrap."""

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.actor_owner_protection import require_owner_change_allowed
from yoke_core.domain.actor_role import ActorRoleRefused, replace_person_role
from yoke_core.domain.actor_role_grants import (
    grant_actor_org_role,
    grant_actor_project_role,
    revoke_actor_project_role,
)


@pytest.fixture
def conn():
    with decision_request_connection() as value:
        for table in ("actor_org_roles", "actor_project_roles"):
            value.execute(f"ALTER TABLE {table} ADD COLUMN granted_by_actor_id INTEGER")
        value.execute("INSERT INTO actor_org_roles VALUES (1, 1, 1, 'now', 1)")
        value.commit()
        yield value


@pytest.mark.parametrize("scope", [("org", 1), ("project", 10)])
@pytest.mark.parametrize("new_role", ["owner", "operator", None, "unchanged"])
def test_admin_cannot_edit_owner_or_grant_owner(conn, scope, new_role):
    target = 1 if scope[0] == "org" else 2
    with pytest.raises(ActorRoleRefused) as refused:
        require_owner_change_allowed(conn, 5, target, scope, new_role)
    assert refused.value.code == "owner_protected"
    assert "Ask an owner" in str(refused.value)


def test_owner_can_grant_owner_but_cannot_remove_last_owner(conn):
    with pytest.raises(ActorRoleRefused) as refused:
        replace_person_role(
            conn,
            actor_id=1,
            org_id=1,
            role="admin",
            granted_by_actor_id=1,
            now=utc_now(),
        )
    assert refused.value.code == "last_owner"
    grant_actor_org_role(
        conn, actor_id=3, org_id=1, role_name="owner", granted_by_actor_id=1
    )
    replace_person_role(
        conn, actor_id=1, org_id=1, role="admin", granted_by_actor_id=3, now=utc_now()
    )
    assert (
        conn.execute(
            "SELECT r.name FROM actor_org_roles ar JOIN roles r "
            "ON r.id=ar.role_id WHERE ar.actor_id=1"
        ).fetchone()[0]
        == "admin"
    )


def test_project_grant_and_revoke_use_owner_protection(conn):
    with pytest.raises(ActorRoleRefused, match="owner_protected"):
        grant_actor_project_role(
            conn, actor_id=3, project_id=10, role_name="owner", granted_by_actor_id=5
        )
    conn.execute("DELETE FROM actor_org_roles WHERE actor_id=1")
    with pytest.raises(ActorRoleRefused, match="last_owner"):
        revoke_actor_project_role(
            conn, actor_id=2, project_id=10, role_name="owner", caller_actor_id=2
        )
    conn.execute("INSERT INTO actor_org_roles VALUES (1, 1, 1, 'now', 1)")
    grant_actor_project_role(
        conn, actor_id=3, project_id=10, role_name="owner", granted_by_actor_id=1
    )
    assert revoke_actor_project_role(
        conn, actor_id=2, project_id=10, role_name="owner", caller_actor_id=3
    )


def test_disabled_owner_stays_protected_and_does_not_satisfy_last_owner(conn):
    conn.execute("INSERT INTO actor_org_roles VALUES (3, 1, 1, 'now', 1)")
    conn.execute("UPDATE actors SET status='disabled' WHERE id=3")
    with pytest.raises(ActorRoleRefused, match="owner_protected"):
        require_owner_change_allowed(conn, 5, 3, ("org", 1), "operator")
    with pytest.raises(ActorRoleRefused, match="last_owner"):
        require_owner_change_allowed(conn, 1, 1, ("org", 1), None)
    with pytest.raises(ActorRoleRefused, match="owner_protected"):
        require_owner_change_allowed(conn, 3, 4, ("org", 1), "owner")


def test_people_cannot_receive_machine_roles_at_project_scope(conn):
    with pytest.raises(ActorRoleRefused, match="machine-only"):
        grant_actor_project_role(
            conn,
            actor_id=3,
            project_id=10,
            role_name="deployment_ci",
            granted_by_actor_id=1,
        )


def test_nonowner_edits_do_not_require_owner(conn):
    require_owner_change_allowed(conn, 5, 4, ("project", 10), "operator")
    require_owner_change_allowed(conn, 5, 4, ("project", 10), "unchanged")

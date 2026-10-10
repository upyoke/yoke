"""A person's one org role: set by actor or member email, with named refusals."""

from __future__ import annotations

import pytest

from yoke_contracts.timestamps import utc_now

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    grant_actor_org_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actor_role import ActorRoleRefused, org_roles_of
from yoke_core.domain.actor_state import set_actor_enabled
from yoke_core.domain.actors import seed_human_actor, seed_system_actor
from yoke_core.domain.control_plane_authority import resolve_control_plane_org_id
from yoke_core.domain.external_identities import link_external_identity
from yoke_core.domain.handlers.actor_role import handle_actor_role_set


def _org(conn):
    seed_roles_and_permissions(conn)
    return resolve_control_plane_org_id(conn)


def _person(conn, name, role, org_id):
    actor_id = seed_human_actor(conn, name)
    grant_actor_org_role(conn, actor_id=actor_id, org_id=org_id, role_name=role)
    return actor_id


def _set(caller, **payload):
    return handle_actor_role_set(
        FunctionCallRequest(
            function="actors.role.set",
            actor=ActorContext(actor_id=str(caller), session_id=""),
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


def _org_roles(conn, actor_id, org_id):
    rows = conn.execute(
        "SELECT r.name FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND aor.org_id = %s",
        (actor_id, org_id),
    ).fetchall()
    return sorted(row[0] for row in rows)


def test_admin_sets_a_person_role_by_actor_id_and_it_replaces_the_old_one(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = _person(test_db, "Member", "operator", org_id)

    result = _set(admin, actor_id=member, role="viewer")

    assert result.primary_success, result.error
    assert result.result_payload == {
        "actor_id": member,
        "role": "viewer",
        "previous_roles": ["operator"],
        "changed": True,
    }
    assert _org_roles(test_db, member, org_id) == ["viewer"]
    repeat = _set(admin, actor_id=member, role="viewer")
    assert repeat.result_payload["changed"] is False


def test_member_email_resolves_the_linked_actor(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = _person(test_db, "Member", "operator", org_id)
    link_external_identity(
        test_db,
        actor_id=member,
        issuer="https://accounts.google.com",
        subject="member-subject",
        email="Member@Example.test",
    )
    test_db.commit()

    result = _set(admin, member_email="member@example.test", role="admin")

    assert result.primary_success, result.error
    assert result.result_payload["actor_id"] == member
    assert _org_roles(test_db, member, org_id) == ["admin"]
    unknown = _set(admin, member_email="nobody@example.test", role="admin")
    assert unknown.error.code == "member_not_linked"
    assert "sign in once" in unknown.error.message


def test_last_active_admin_cannot_be_demoted(test_db):
    org_id = _org(test_db)
    for (actor_id,) in test_db.execute(
        "SELECT aor.actor_id FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE r.name = 'admin'"
    ).fetchall():
        test_db.execute("DELETE FROM actor_org_roles WHERE actor_id = %s", (actor_id,))
    test_db.commit()
    admin = _person(test_db, "Admin", "admin", org_id)
    other = _person(test_db, "Other", "admin", org_id)
    set_actor_enabled(
        test_db, actor_id=other, caller_actor_id=admin, enabled=False, now=utc_now()
    )

    refused = _set(admin, actor_id=admin, role="operator")

    assert refused.error.code == "last_admin"
    assert "make another active person admin first" in refused.error.message
    assert _org_roles(test_db, admin, org_id) == ["admin"]
    with pytest.raises(ActorRoleRefused, match="last active admin"):
        grant_actor_org_role(test_db, actor_id=admin, org_id=org_id, role_name="viewer")


@pytest.mark.parametrize(
    ("role", "code"),
    [
        ("deployment_ci", "machine_only_role"),
        ("migration_verification_ci", "machine_only_role"),
        ("owner", "role_not_assignable"),
        ("member", "role_not_assignable"),
    ],
)
def test_roles_a_person_cannot_hold_are_refused_by_name(test_db, role, code):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = _person(test_db, "Member", "operator", org_id)

    refused = _set(admin, actor_id=member, role=role)

    assert refused.error.code == code
    assert "admin, operator, viewer" in refused.error.message
    assert org_roles_of(test_db, member, org_id) == ["operator"]


def test_system_actors_and_non_admins_are_refused(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    operator = _person(test_db, "Operator", "operator", org_id)
    system = seed_system_actor(test_db, "deploy-ci")

    assert _set(admin, actor_id=system, role="viewer").error.code == "actor_not_human"
    assert (
        _set(operator, actor_id=admin, role="viewer").error.code == "permission_denied"
    )
    both = _set(admin, actor_id=operator, member_email="a@example.test", role="admin")
    assert both.error.code == "payload_invalid"


def test_system_actor_org_grants_accumulate(test_db):
    org_id = _org(test_db)
    system = seed_system_actor(test_db, "verifier")
    grant_actor_org_role(test_db, actor_id=system, org_id=org_id, role_name="admin")
    grant_actor_org_role(
        test_db, actor_id=system, org_id=org_id, role_name="migration_verification_ci"
    )
    assert _org_roles(test_db, system, org_id) == ["admin", "migration_verification_ci"]


def test_a_person_still_holding_several_roles_converges_onto_the_one_set(test_db):
    org_id = _org(test_db)
    admin = _person(test_db, "Admin", "admin", org_id)
    member = _person(test_db, "Member", "operator", org_id)
    test_db.execute(
        "INSERT INTO actor_org_roles (actor_id, org_id, role_id, granted_at) "
        "SELECT %s, %s, id, '2026-01-01T00:00:00Z' FROM roles WHERE name = 'admin'",
        (member, org_id),
    )
    test_db.commit()

    result = _set(admin, actor_id=member, role="operator")

    assert result.primary_success, result.error
    assert result.result_payload["previous_roles"] == ["admin", "operator"]
    assert result.result_payload["changed"] is True
    assert _org_roles(test_db, member, org_id) == ["operator"]

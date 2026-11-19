"""An org-scoped denial names the member's role and who can change it.

An org operator who ran ``yoke onboard project`` was told their API token
lacked ``project.create``. Machine tokens carry no scopes: the cause is the
org role, so the denial names the role held, the roles that allow creating a
project, and the command an owner or admin runs to change it. A denial for an
actor with no org role, and the single-owner universe whose operator lacks
its grant, keep their own wording.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.actor_permissions import (
    PERM_PROJECT_CREATE,
    PermissionDenied,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    require_org_permission,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.local_operating_actor import OPERATING_ACTOR_GRANT_REPAIR
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn():
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
    create_core_tables(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    create_auth_tables(c)
    seed_default_org(c)
    seed_roles_and_permissions(c)
    yield c
    c.close()


def _org_id(conn) -> int:
    return int(conn.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()[0])


def _person(conn, name: str, role: str | None = None) -> int:
    actor_id = int(
        conn.execute(
            "INSERT INTO actors (kind, name, created_at) "
            "VALUES ('human', %s, '2026-01-01T00:00:00Z') RETURNING id",
            (name,),
        ).fetchone()[0]
    )
    conn.commit()
    if role is not None:
        # Seed the fixture role directly; grant authorization has its own tests.
        conn.execute(
            "INSERT INTO actor_org_roles (actor_id, org_id, role_id, granted_at) "
            "SELECT %s, %s, id, NOW() FROM roles WHERE name = %s",
            (actor_id, _org_id(conn), role),
        )
        conn.commit()
    return actor_id


def _denial(conn, actor_id: int) -> str:
    with pytest.raises(PermissionDenied) as raised:
        require_org_permission(
            conn,
            actor_id=actor_id,
            org_id=_org_id(conn),
            permission_key=PERM_PROJECT_CREATE,
        )
    return str(raised.value)


def test_org_operator_denied_project_create_reads_the_role_recovery(conn):
    _person(conn, "Org Owner", ROLE_OWNER)
    operator = _person(conn, "Dana Lee", ROLE_OPERATOR)

    message = _denial(conn, operator)

    assert message.startswith(f"actor {operator} lacks 'project.create' on org ")
    assert message.endswith(
        ". Dana Lee holds org role operator; creating a project needs org role "
        "owner or admin. Ask an org owner or admin to do it for you, or to "
        "change your role with `yoke actors role set --member EMAIL --role admin`."
    )
    assert "token" not in message.lower()
    assert OPERATING_ACTOR_GRANT_REPAIR not in message


def test_an_unnamed_member_is_named_by_actor_id(conn):
    _person(conn, "Org Owner", ROLE_OWNER)
    operator = _person(conn, "", ROLE_OPERATOR)

    assert f"actor {operator} holds org role operator;" in _denial(conn, operator)


def test_owner_and_admin_create_projects(conn):
    owner = _person(conn, "Org Owner", ROLE_OWNER)
    admin = _person(conn, "Org Admin", ROLE_ADMIN)
    for actor_id in (owner, admin):
        decision = require_org_permission(
            conn,
            actor_id=actor_id,
            org_id=_org_id(conn),
            permission_key=PERM_PROJECT_CREATE,
        )
        assert decision.allowed


def test_actor_with_no_org_role_keeps_the_plain_denial(conn):
    _person(conn, "Org Owner", ROLE_OWNER)
    stranger = _person(conn, "Stranger")

    message = _denial(conn, stranger)

    assert message.endswith(f"(id {_org_id(conn)})")
    assert "holds org role" not in message


def test_single_owner_universe_keeps_the_grant_repair(conn):
    """The only human, lacking org admin, is told the local repair instead."""
    sole = _person(conn, "Machine Owner", ROLE_OPERATOR)

    message = _denial(conn, sole)

    assert OPERATING_ACTOR_GRANT_REPAIR in message
    assert "holds org role" not in message

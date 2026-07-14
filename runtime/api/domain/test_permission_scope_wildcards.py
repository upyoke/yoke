"""Scope-aware permission model: org-admin + project-owner wildcards and the
org-target check path (auth scope refactor).

Locks the security-critical invariants:
  * org admin is all-access by construction (drift-proof),
  * a project owner gets every *project-grantable* permission on its *own*
    project only — never org-scoped permissions, never another project,
  * the org-target check requires an org admin (a project owner, even yoke's,
    is not one),
  * project grants remain project-scoped even for permissions such as raw DB
    read; whole-universe dispatch separately requires org-admin authority.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    PERM_PROJECT_CREATE,
    PermissionDenied,
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    org_permission_decision,
    permission_decision,
    require_org_permission,
    require_permission,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn():
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    create_core_tables(c)
    seed_project_identities(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    create_auth_tables(c)
    seed_default_org(c)
    seed_roles_and_permissions(c)
    yield c
    c.close()


def _new_actor(conn) -> int:
    cur = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-01-01T00:00:00Z') RETURNING id"
    )
    actor_id = int(cur.fetchone()[0])
    conn.commit()
    return actor_id


def _org_of(conn, project_id: int) -> int:
    row = conn.execute(
        "SELECT org_id FROM projects WHERE id = %s", (project_id,)
    ).fetchone()
    return int(row[0])


def _allowed(conn, actor_id, project_id, perm) -> bool:
    return permission_decision(
        conn, actor_id=actor_id, project_id=project_id, permission_key=perm
    ).allowed


def test_org_admin_wildcard_allows_any_permission_any_project(conn):
    yoke = resolve_project_id(conn, "yoke")
    buzz = resolve_project_id(conn, "buzz")
    admin = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=admin, org_id=_org_of(conn, yoke),
        role_name=ROLE_ADMIN, granted_by_actor_id=admin,
    )
    assert _allowed(conn, admin, yoke, PERM_DB_READ_RAW)
    assert _allowed(conn, admin, buzz, PERM_ITEMS_WRITE)
    assert _allowed(conn, admin, buzz, PERM_DB_READ_RAW)
    assert _allowed(conn, admin, yoke, PERM_ORG_ADMIN)


def test_project_owner_wildcard_own_project_and_grantable_perms_only(conn):
    yoke = resolve_project_id(conn, "yoke")
    buzz = resolve_project_id(conn, "buzz")
    buzz_owner = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=buzz_owner, project_id=buzz,
        role_name=ROLE_OWNER, granted_by_actor_id=buzz_owner,
    )
    assert _allowed(conn, buzz_owner, buzz, PERM_ITEMS_WRITE)
    assert _allowed(conn, buzz_owner, buzz, PERM_DB_READ_RAW)
    assert not _allowed(conn, buzz_owner, buzz, PERM_ORG_ADMIN)
    assert not _allowed(conn, buzz_owner, buzz, PERM_PROJECT_CREATE)
    assert not _allowed(conn, buzz_owner, yoke, PERM_ITEMS_WRITE)


def test_raw_db_permission_project_grants_do_not_cross_projects(conn):
    yoke = resolve_project_id(conn, "yoke")
    buzz = resolve_project_id(conn, "buzz")
    buzz_owner = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=buzz_owner, project_id=buzz,
        role_name=ROLE_OWNER, granted_by_actor_id=buzz_owner,
    )
    yoke_owner = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=yoke_owner, project_id=yoke,
        role_name=ROLE_OWNER, granted_by_actor_id=yoke_owner,
    )
    org_admin = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=org_admin, org_id=_org_of(conn, yoke),
        role_name=ROLE_ADMIN, granted_by_actor_id=org_admin,
    )
    assert not _allowed(conn, buzz_owner, yoke, PERM_DB_READ_RAW)  # closed hole
    assert _allowed(conn, yoke_owner, yoke, PERM_DB_READ_RAW)    # case 2
    assert _allowed(conn, org_admin, yoke, PERM_DB_READ_RAW)       # root


def test_no_role_actor_denied_everything(conn):
    yoke = resolve_project_id(conn, "yoke")
    nobody = _new_actor(conn)
    assert not _allowed(conn, nobody, yoke, PERM_ITEMS_WRITE)
    assert not _allowed(conn, nobody, yoke, PERM_DB_READ_RAW)


def test_org_target_check_requires_org_admin(conn):
    yoke = resolve_project_id(conn, "yoke")
    org_id = _org_of(conn, yoke)
    org_admin = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=org_admin, org_id=org_id,
        role_name=ROLE_ADMIN, granted_by_actor_id=org_admin,
    )
    yoke_owner = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=yoke_owner, project_id=yoke,
        role_name=ROLE_OWNER, granted_by_actor_id=yoke_owner,
    )
    assert org_permission_decision(
        conn, actor_id=org_admin, org_id=org_id, permission_key=PERM_ORG_ADMIN
    ).allowed
    assert org_permission_decision(
        conn, actor_id=org_admin, org_id=org_id, permission_key=PERM_PROJECT_CREATE
    ).allowed
    assert not org_permission_decision(
        conn, actor_id=yoke_owner, org_id=org_id, permission_key=PERM_ORG_ADMIN
    ).allowed


def _org_name(conn, org_id: int) -> str:
    return str(
        conn.execute(
            "SELECT name FROM organizations WHERE id = %s", (org_id,)
        ).fetchone()[0]
    )


def _project_name(conn, project_id: int) -> str:
    return str(
        conn.execute(
            "SELECT name FROM projects WHERE id = %s", (project_id,)
        ).fetchone()[0]
    )


def test_require_org_permission_denial_names_the_org(conn):
    """An org-scoped denial includes the org name, not just the numeric id."""
    yoke = resolve_project_id(conn, "yoke")
    org_id = _org_of(conn, yoke)
    nobody = _new_actor(conn)
    with pytest.raises(PermissionDenied) as exc_info:
        require_org_permission(
            conn, actor_id=nobody, org_id=org_id, permission_key=PERM_PROJECT_CREATE
        )
    message = str(exc_info.value)
    assert f"actor {nobody} lacks" in message
    assert PERM_PROJECT_CREATE in message
    assert _org_name(conn, org_id) in message
    assert f"(id {org_id})" in message


def test_require_org_permission_falls_back_to_id_for_missing_org(conn):
    """A denial against an org with no row reports the id without raising."""
    nobody = _new_actor(conn)
    missing_org_id = 999999
    with pytest.raises(PermissionDenied) as exc_info:
        require_org_permission(
            conn, actor_id=nobody, org_id=missing_org_id,
            permission_key=PERM_ORG_ADMIN,
        )
    assert f"on org {missing_org_id}" in str(exc_info.value)


def test_require_permission_denial_names_the_project(conn):
    """A project-scoped denial includes the project name and slug, not just id."""
    buzz = resolve_project_id(conn, "buzz")
    nobody = _new_actor(conn)
    with pytest.raises(PermissionDenied) as exc_info:
        require_permission(
            conn, actor_id=nobody, project_id=buzz, permission_key=PERM_ITEMS_WRITE
        )
    message = str(exc_info.value)
    assert f"actor {nobody} lacks" in message
    assert PERM_ITEMS_WRITE in message
    assert _project_name(conn, buzz) in message
    assert f"(buzz, id {buzz})" in message


def test_require_permission_falls_back_to_id_for_missing_project(conn):
    """A denial against a project with no row reports the id without raising."""
    nobody = _new_actor(conn)
    missing_project_id = 999999
    with pytest.raises(PermissionDenied) as exc_info:
        require_permission(
            conn, actor_id=nobody, project_id=missing_project_id,
            permission_key=PERM_ITEMS_WRITE,
        )
    assert f"on project {missing_project_id}" in str(exc_info.value)

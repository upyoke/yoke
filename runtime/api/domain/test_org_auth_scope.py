"""Org auth scope behavior on the real Postgres control plane.

Permission resolution, org/project grant scoping, and the org-then-project
decision rule are authority behavior — they run against the Postgres control
plane in production, so they are proven here against a disposable real-Postgres
database (``test_db``; conftest binds the local cluster). The legacy ->
post-migration *transition* is rehearsed separately in
``test_org_auth_scope_postgres.py``.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_WRITE,
    PERM_ORG_ADMIN,
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    permission_decision,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.org_schema import (
    DEFAULT_ORG_SLUG,
    org_id_by_slug,
    seed_default_org,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities


@pytest.fixture()
def authdb(test_db):
    """Disposable Postgres DB with projects, the role/permission catalog, and the
    default org seeded idempotently on top of the canonical schema."""
    conn = test_db
    seed_project_identities(conn)
    seed_roles_and_permissions(conn)
    seed_default_org(conn)
    conn.commit()
    return conn


def test_org_tables_and_project_association(authdb):
    org_id = org_id_by_slug(authdb, DEFAULT_ORG_SLUG)
    assert org_id is not None
    nulls = authdb.execute(
        "SELECT COUNT(*) FROM projects WHERE org_id IS NULL"
    ).fetchone()[0]
    assert nulls == 0


def test_owner_role_lacks_org_admin(authdb):
    row = authdb.execute(
        "SELECT COUNT(*) FROM roles r "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions p ON p.id = rp.permission_id "
        "WHERE r.name = %s AND p.key = %s",
        (ROLE_OWNER, PERM_ORG_ADMIN),
    ).fetchone()[0]
    assert row == 0


def test_org_admin_implies_all_project_permissions(authdb):
    actor_id = seed_human_actor(authdb)
    org_id = org_id_by_slug(authdb, DEFAULT_ORG_SLUG)
    grant_actor_org_role(authdb, actor_id=actor_id, org_id=org_id, role_name=ROLE_ADMIN)
    yoke_id = resolve_project_id(authdb, "yoke")
    # No project grant exists — org admin alone authorizes a project write.
    decision = permission_decision(
        authdb, actor_id=actor_id, project_id=yoke_id, permission_key=PERM_ITEMS_WRITE
    )
    assert decision.allowed
    assert ROLE_ADMIN in decision.role_names


def test_project_grant_still_scopes_to_one_project(authdb):
    actor_id = seed_human_actor(authdb)
    yoke_id = resolve_project_id(authdb, "yoke")
    buzz_id = resolve_project_id(authdb, "buzz")
    grant_actor_project_role(
        authdb, actor_id=actor_id, project_id=yoke_id, role_name=ROLE_OPERATOR
    )
    assert permission_decision(
        authdb, actor_id=actor_id, project_id=yoke_id, permission_key=PERM_ITEMS_WRITE
    ).allowed
    # No grant on buzz, and no org grant -> denied there.
    assert not permission_decision(
        authdb, actor_id=actor_id, project_id=buzz_id, permission_key=PERM_ITEMS_WRITE
    ).allowed

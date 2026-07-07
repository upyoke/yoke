"""Focused coverage for cloud-runtime actor-token auth primitives."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_permissions import (
    PERM_ITEMS_READ,
    PERM_ITEMS_WRITE,
    ROLE_OWNER,
    ROLE_VIEWER,
    PermissionDenied,
    grant_actor_project_role,
    require_permission,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import resolve_actor_by_label, seed_human_actor
from yoke_core.domain.api_tokens import (
    TOKEN_PREFIX,
    TokenNotFound,
    TokenRevoked,
    bootstrap_admin_token,
    mint_token,
    revoke_token,
    verify_token,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn() -> Iterator[Any]:
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    try:
        create_core_tables(c)
        seed_project_identities(c)
        create_path_registry_tables(c)
        create_actor_path_claim_tables(c)
        create_auth_tables(c)
        seed_roles_and_permissions(c)
        c.commit()
        yield c
    finally:
        c.close()
        pg_testdb.drop_test_database(name)


def test_actor_roles_allow_multiple_projects_and_deny_missing_role(conn):
    actor_id = seed_human_actor(conn)
    yoke_id = resolve_project_id(conn, "yoke")
    buzz_id = resolve_project_id(conn, "buzz")
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=yoke_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=buzz_id,
        role_name=ROLE_VIEWER,
        granted_by_actor_id=actor_id,
    )

    assert require_permission(
        conn, actor_id=actor_id, project_id=yoke_id, permission_key=PERM_ITEMS_WRITE
    ).allowed
    assert require_permission(
        conn, actor_id=actor_id, project_id=buzz_id, permission_key=PERM_ITEMS_READ
    ).allowed
    with pytest.raises(PermissionDenied):
        require_permission(
            conn,
            actor_id=actor_id,
            project_id=buzz_id,
            permission_key=PERM_ITEMS_WRITE,
        )


def test_token_hash_verify_audit_and_revoke(conn):
    actor_id = seed_human_actor(conn)
    created = mint_token(conn, actor_id=actor_id, name="dev-machine")

    assert created.raw_token.startswith(TOKEN_PREFIX)
    stored = conn.execute(
        "SELECT token_hash FROM api_tokens WHERE id = %s",
        (created.token_id,),
    ).fetchone()[0]
    assert stored != created.raw_token

    verified = verify_token(conn, created.raw_token)
    assert verified.actor_id == actor_id
    audit_count = conn.execute(
        "SELECT COUNT(*) FROM api_token_audit WHERE api_token_id = %s",
        (created.token_id,),
    ).fetchone()[0]
    assert audit_count >= 2

    revoke_token(conn, token_id=created.token_id, actor_id=actor_id)
    with pytest.raises(TokenRevoked):
        verify_token(conn, created.raw_token)
    with pytest.raises(TokenNotFound):
        verify_token(conn, f"{TOKEN_PREFIX}missing")


def test_token_prefix_is_yoke_branded_and_body_is_dash_free():
    """The prefix is yoke_v1_ (no legacy-prefix residue) and the random body
    contains no '-', so the whole token is a single double-click-selectable
    word (a dash is a word boundary in terminals and browsers)."""
    from yoke_core.domain.api_tokens import generate_token

    assert TOKEN_PREFIX == "yoke_v1_"
    for _ in range(200):
        token = generate_token()
        assert token.startswith("yoke_v1_")
        assert "-" not in token, f"token contains a dash (breaks copy): {token!r}"


def test_bootstrap_admin_token_grants_org_admin_without_storing_raw_secret(conn):
    """Default shape: neutral admin label + all-access org admin grant."""
    from yoke_core.domain.api_tokens import DEFAULT_ADMIN_ACTOR_LABEL

    created = bootstrap_admin_token(conn)
    actor_id = resolve_actor_by_label(conn, DEFAULT_ADMIN_ACTOR_LABEL)
    assert actor_id == created.actor_id
    # Org admin is the all-access root identity: project-scoped permission
    # checks pass on any project the org owns.
    yoke_id = resolve_project_id(conn, "yoke")
    decision = require_permission(
        conn,
        actor_id=created.actor_id,
        project_id=yoke_id,
        permission_key=PERM_ITEMS_WRITE,
    )
    assert decision.allowed
    assert decision.role_names == ("admin",)
    rows = conn.execute(
        "SELECT COUNT(*) FROM api_tokens WHERE token_hash = %s",
        (created.raw_token,),
    ).fetchone()
    assert rows[0] == 0


def test_bootstrap_admin_token_project_slug_grants_project_owner(conn):
    """Explicit project shape keeps the narrower project-owner grant."""
    created = bootstrap_admin_token(
        conn, actor_label="ops-lead", project="yoke",
    )
    yoke_id = resolve_project_id(conn, "yoke")
    decision = require_permission(
        conn,
        actor_id=created.actor_id,
        project_id=yoke_id,
        permission_key=PERM_ITEMS_WRITE,
    )
    assert decision.allowed
    assert decision.role_names == ("owner",)
    org_roles = conn.execute(
        "SELECT COUNT(*) FROM actor_org_roles WHERE actor_id = %s",
        (created.actor_id,),
    ).fetchone()
    assert int(org_roles[0]) == 0

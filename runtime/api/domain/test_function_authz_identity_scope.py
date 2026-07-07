"""Dispatch authorization for the identity.* admin family.

Every identity function (reads included — invite listings expose member
emails) is org-scoped and requires ``org.admin`` on the target org. A
fresh self-host universe carries no ``yoke`` project, so the org-context
resolver falls back to the identity-card org for such requests.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from runtime.api.fixtures import pg_testdb

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import (
    create_external_identity_tables,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.schema_init_tables import create_core_tables
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.function_target_resolution import resolve_org_context
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )
    create_core_tables(c)
    seed_project_identities(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    create_auth_tables(c)
    create_external_identity_tables(c)
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


def _entry(function_id: str, *, side_effects: bool = True) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("global",),
        side_effects=("db_write",) if side_effects else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(actor_id, function_id: str, payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _default_org(conn) -> int:
    return int(
        conn.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()[0]
    )


@pytest.mark.parametrize(
    "function_id, side_effects",
    [
        ("identity.invite.create", True),
        ("identity.invite.list", False),
        ("identity.invite.revoke", True),
        ("identity.link.set", True),
        ("identity.autojoin.set", True),
    ],
)
def test_identity_family_requires_org_admin(conn, function_id, side_effects):
    org_id = _default_org(conn)
    admin = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=admin, org_id=org_id,
        role_name=ROLE_ADMIN, granted_by_actor_id=admin,
    )
    outsider = _new_actor(conn)
    entry = _entry(function_id, side_effects=side_effects)

    allowed = check_dispatch_permission(conn, entry, _request(admin, function_id))
    assert allowed.error is None

    denied = check_dispatch_permission(conn, entry, _request(outsider, function_id))
    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"


def test_project_owner_is_not_enough_for_identity_admin(conn):
    yoke = resolve_project_id(conn, "yoke")
    owner = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=owner, project_id=yoke,
        role_name=ROLE_OWNER, granted_by_actor_id=owner,
    )
    entry = _entry("identity.invite.create")
    denied = check_dispatch_permission(
        conn, entry, _request(owner, "identity.invite.create"),
    )
    assert denied.error is not None


def test_org_context_falls_back_to_identity_card_org_without_yoke_project(conn):
    # Simulate a fresh self-host universe: no projects registered at all.
    conn.execute("DELETE FROM actor_project_roles")
    conn.execute("DELETE FROM projects")
    conn.commit()
    org_id = _default_org(conn)
    admin = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=admin, org_id=org_id,
        role_name=ROLE_ADMIN, granted_by_actor_id=admin,
    )
    request = _request(admin, "identity.invite.create", {"email": "a@b.co"})
    assert resolve_org_context(conn, request) == org_id
    entry = _entry("identity.invite.create")
    assert check_dispatch_permission(conn, entry, request).error is None
    # An explicit project ref that cannot resolve still refuses.
    explicit = _request(
        admin, "identity.invite.create", {"project": "no-such-project"},
    )
    assert resolve_org_context(conn, explicit) is None

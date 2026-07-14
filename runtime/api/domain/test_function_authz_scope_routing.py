"""Dispatch-level routing tests for scope-aware function authorization.

``function_authz_scope.classify`` sorts every registered function into one
scope bucket; ``check_dispatch_permission`` routes the permission check
accordingly, against the token-verified actor identity (never the session or
workspace). This locks each routing edge:

Enforcement applies only when a verified numeric actor is present (the cloud
boundary sets it from the token; a missing actor is local/advisory context and
is permissive). With an actor:

  * control-plane  -> checked against the universe's sole organization; only
    its org admin is allowed and project slugs confer no authority,
  * org            -> checked against the target org (org admin),
  * project        -> the op's real target project, with NO fallback: an
    existing target resolves to its real project and is checked; an
    unresolvable target is denied before the handler, never silently aimed at yoke,
  * deny           -> an unclassified *side-effecting* function fails closed,
  * client-local / actor-session -> allowed.

Without a verified actor every scope is permissive (local/advisory).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from yoke_core.domain.actor_permissions import (
    ROLE_ADMIN,
    ROLE_OWNER,
    grant_actor_org_role,
    grant_actor_project_role,
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
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import RegistryEntry


class EmptyModel(BaseModel):
    pass


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


def _project_owner(conn, project_id: int) -> int:
    actor_id = _new_actor(conn)
    grant_actor_project_role(
        conn, actor_id=actor_id, project_id=project_id,
        role_name=ROLE_OWNER, granted_by_actor_id=actor_id,
    )
    return actor_id


def _org_admin(conn, org_id: int) -> int:
    actor_id = _new_actor(conn)
    grant_actor_org_role(
        conn, actor_id=actor_id, org_id=org_id,
        role_name=ROLE_ADMIN, granted_by_actor_id=actor_id,
    )
    return actor_id


def _entry(function_id: str, *, side_effects: bool = True) -> RegistryEntry:
    return RegistryEntry(
        function_id=function_id,
        handler=lambda _request: None,
        request_model=EmptyModel,
        response_model=EmptyModel,
        stability="stable",
        owner_module=__name__,
        target_kinds=("item",),
        side_effects=("db_write",) if side_effects else (),
        emitted_event_names=(),
        guardrails=(),
        adapter_status="live",
    )


def _request(
    actor_id, function_id: str, *, project: str | None = None
) -> FunctionCallRequest:
    target = (
        TargetRef(kind="item", project_id=project)
        if project is not None
        else TargetRef(kind="global")
    )
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=target,
        payload={},
    )


def _no_actor_request(function_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="", session_id="s-1"),
        target=TargetRef(kind="global"),
        payload={},
    )


def _payload_request(actor_id, function_id: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_projects_list_allows_project_owner_for_actor_visible_handler_filter(conn):
    yoke = resolve_project_id(conn, "yoke")
    org_id = _org_of(conn, yoke)
    org_admin = _org_admin(conn, org_id)
    yoke_owner = _project_owner(conn, yoke)
    entry = _entry("projects.list", side_effects=False)

    assert check_dispatch_permission(conn, entry, _request(org_admin, "projects.list")).error is None
    assert check_dispatch_permission(conn, entry, _request(yoke_owner, "projects.list")).error is None


def test_org_scoped_op_requires_org_admin(conn):
    yoke = resolve_project_id(conn, "yoke")
    org_id = _org_of(conn, yoke)
    org_admin = _org_admin(conn, org_id)
    yoke_owner = _project_owner(conn, yoke)
    entry = _entry("deployment_flows.get", side_effects=False)

    assert check_dispatch_permission(conn, entry, _request(org_admin, "deployment_flows.get")).error is None

    # A project owner — even yoke's — is not an org admin.
    denied = check_dispatch_permission(conn, entry, _request(yoke_owner, "deployment_flows.get"))
    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"


def test_project_op_without_resolvable_target_is_denied_without_fallback(conn):
    yoke = resolve_project_id(conn, "yoke")
    actor_id = _project_owner(conn, yoke)
    cases = [
        (
            _entry("items.structured_field.replace"),
            FunctionCallRequest(
                function="items.structured_field.replace",
                actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
                target=TargetRef(kind="global"),
                payload={},
            ),
        ),
        (
            _entry("projects.get", side_effects=False),
            _payload_request(actor_id, "projects.get", {"project": "ghost"}),
        ),
    ]
    for entry, request in cases:
        res = check_dispatch_permission(conn, entry, request)
        assert res.error is not None and res.error.error is not None
        assert (res.error.error.code, res.project_id) == ("permission_denied", None)


def test_every_registered_function_is_explicitly_classified():
    # Coverage guard: no live function may fall through to the fail-closed DENY
    # default. Every registered function must be intentionally classified — by
    # permission_key_for (PROJECT), or an explicit _BY_ID / _BY_PREFIX entry.
    # A new function that forgets classification trips this in CI, which is the
    # forcing function for correct-by-construction permissions.
    from yoke_core.domain.function_authz_scope import (
        DENY,
        classify,
        permission_key_for,
    )
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import list_entries

    register_all_handlers()  # idempotent; populates the registry if empty
    unclassified = sorted(
        e.function_id
        for e in list_entries()
        if classify(
            e.function_id,
            side_effects=bool(e.side_effects),
            project_permission=permission_key_for(e),
        ).scope == DENY
    )
    assert not unclassified, (
        "registered functions fall through to the fail-closed DENY default — "
        f"classify each in function_authz_scope: {unclassified}"
    )


def test_board_data_get_resolves_project_from_payload_scope(conn):
    # board.data.get names its project in payload.scope; it must resolve + be
    # checked against that project (not bypassed), so cross-project board reads
    # are denied.
    buzz = resolve_project_id(conn, "buzz")
    buzz_owner = _project_owner(conn, buzz)
    entry = _entry("board.data.get", side_effects=False)
    allowed = check_dispatch_permission(
        conn, entry, _payload_request(buzz_owner, "board.data.get", {"scope": "buzz"}),
    )
    assert allowed.error is None
    assert allowed.project_slug == "buzz"
    denied = check_dispatch_permission(
        conn, entry, _payload_request(buzz_owner, "board.data.get", {"scope": "yoke"}),
    )
    assert denied.error is not None


def test_payload_named_project_target_hint_must_match_payload(conn):
    buzz = resolve_project_id(conn, "buzz")
    buzz_owner = _project_owner(conn, buzz)
    entry = _entry("projects.update")

    denied = check_dispatch_permission(
        conn,
        entry,
        FunctionCallRequest(
            function="projects.update",
            actor=ActorContext(actor_id=str(buzz_owner), session_id="s-1"),
            target=TargetRef(kind="global", project_id="yoke"),
            payload={"slug": "buzz", "name": "Buzz"},
        ),
    )

    assert denied.error is not None
    assert denied.error.error.code == "permission_denied"


def test_unclassified_side_effecting_function_fails_closed(conn):
    actor_id = _new_actor(conn)
    entry = _entry("totally.unknown.sideeffecting.op")
    res = check_dispatch_permission(
        conn, entry, _request(actor_id, "totally.unknown.sideeffecting.op", project="yoke")
    )
    assert res.error is not None
    assert "denied by default" in res.error.error.message


def test_client_local_op_allowed_without_actor(conn):
    entry = _entry("auth.set.run")
    res = check_dispatch_permission(conn, entry, _no_actor_request("auth.set.run"))
    assert res.error is None
    assert res.permission_key is None


def test_actor_session_op_allowed_with_actor(conn):
    actor_id = _new_actor(conn)
    entry = _entry("sessions.touch")
    assert check_dispatch_permission(
        conn, entry, _request(actor_id, "sessions.touch")
    ).error is None


def test_no_verified_actor_is_permissive_local(conn):
    # No numeric actor -> local/advisory context -> permissive for every scope.
    # A project-scoped write that WOULD be denied with a non-owning actor is
    # allowed when there is no verified actor at all.
    project_op = _entry("items.structured_field.replace")
    assert check_dispatch_permission(
        conn, project_op, _no_actor_request("items.structured_field.replace")
    ).error is None
    # ...and even an unclassified side-effecting op (the DENY bucket) is
    # permissive locally — DENY only fires once a verified actor is present.
    unclassified = _entry("totally.unknown.sideeffecting.op")
    assert check_dispatch_permission(
        conn, unclassified, _no_actor_request("totally.unknown.sideeffecting.op")
    ).error is None


def test_projects_create_is_org_scoped_update_is_project_scoped(conn):
    yoke = resolve_project_id(conn, "yoke")
    buzz = resolve_project_id(conn, "buzz")
    org_admin = _org_admin(conn, _org_of(conn, yoke))
    buzz_owner = _project_owner(conn, buzz)

    # projects.create is org-scoped: an org admin may register; a project
    # owner (even of an existing project) may not.
    create = _entry("projects.create")
    create_payload = {"slug": "newproj", "name": "New"}
    assert check_dispatch_permission(
        conn, create, _payload_request(org_admin, "projects.create", create_payload)
    ).error is None
    assert check_dispatch_permission(
        conn, create, _payload_request(buzz_owner, "projects.create", create_payload)
    ).error is not None

    # projects.update is project-scoped on the TARGET resolved from payload slug:
    # buzz's owner may update buzz, but not yoke.
    update = _entry("projects.update")
    res = check_dispatch_permission(
        conn, update,
        _payload_request(buzz_owner, "projects.update",
                         {"slug": "buzz", "name": "Buzz"}),
    )
    assert res.error is None
    assert res.project_slug == "buzz"
    assert check_dispatch_permission(
        conn, update,
        _payload_request(buzz_owner, "projects.update",
                         {"slug": "yoke", "name": "Yoke"}),
    ).error is not None

"""Every way a caller can fail to be the hosted service identity is refused."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api.http_auth import HttpAuthContext, authenticate_request
from yoke_core.api.routes.functions import _service_token_guard_response
from yoke_core.domain import machine_approval_requests as approvals
from yoke_core.domain.actor_permissions import (
    role_id_by_name,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor, seed_system_actor
from yoke_core.domain.api_tokens import (
    bootstrap_hosted_service_token,
    mint_token,
)
from yoke_core.domain.function_org_context_resolution import resolve_org_context
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.hosted_service_authority import ROLE_HOSTED_SERVICE
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

_LIFECYCLE = "projects.github_binding.lifecycle"
_AUTH_ID = "5b234860-c927-46ab-b19a-9fb36df056aa"


@pytest.fixture()
def tokendb(test_db):
    seed_project_identities(test_db)
    seed_roles_and_permissions(test_db)
    test_db.commit()
    return test_db


@pytest.fixture()
def registry():
    reset_registry_for_tests()
    register_all_handlers()
    try:
        yield
    finally:
        reset_registry_for_tests()


def _guard(actor_id: int, conn=None):
    kwargs = {} if conn is None else {"conn": conn}
    return _service_token_guard_response(
        {"function": _LIFECYCLE},
        lookup(_LIFECYCLE),
        HttpAuthContext(token_id=1, actor_id=actor_id, token_name="hosted-service"),
        **kwargs,
    )


def _grant_service_role(conn, actor_id: int) -> None:
    conn.execute(
        "INSERT INTO actor_org_roles (actor_id, org_id, role_id, granted_at) "
        "VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')",
        (actor_id, seed_default_org(conn), role_id_by_name(conn, ROLE_HOSTED_SERVICE)),
    )
    conn.commit()


def test_guard_refuses_a_disabled_service_actor(tokendb, registry) -> None:
    service = bootstrap_hosted_service_token(tokendb)
    tokendb.execute(
        "UPDATE actors SET status = 'disabled' WHERE id = %s", (service.actor_id,)
    )
    tokendb.commit()
    assert _guard(service.actor_id, tokendb) is not None


@pytest.mark.parametrize("kind", ("human", "other_system"))
def test_guard_refuses_a_non_service_actor_holding_the_role(
    tokendb, registry, kind
) -> None:
    actor_id = (
        seed_human_actor(tokendb, "role-holder")
        if kind == "human"
        else seed_system_actor(tokendb, "some_other_component")
    )
    _grant_service_role(tokendb, actor_id)
    assert _guard(actor_id, tokendb) is not None


def test_guard_without_a_connection_reads_the_serving_database(
    tokendb, registry
) -> None:
    service = bootstrap_hosted_service_token(tokendb)
    human = seed_human_actor(tokendb, "member")
    assert _guard(service.actor_id) is None
    assert _guard(human) is not None


def _dispatch_request(actor_id: int, function: str, payload=None):
    return FunctionCallRequest(
        function=function,
        target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=str(actor_id), session_id="hosted-service"),
        payload=payload or {},
    )


@pytest.mark.parametrize(
    "function",
    ("profile.token.create", "decision_requests.create", "inbox.list"),
)
def test_service_inherits_no_signed_in_baseline(tokendb, registry, function) -> None:
    service = bootstrap_hosted_service_token(tokendb)
    permission = check_dispatch_permission(
        tokendb, lookup(function), _dispatch_request(service.actor_id, function)
    )
    assert permission.error is not None
    assert permission.error.error.code == "permission_denied"
    assert "outside the hosted service identity's scope" in (
        permission.error.error.message
    )


def _http_request(path: str, raw_token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"authorization", f"Bearer {raw_token}".encode())],
            "query_string": b"",
        }
    )


def test_service_token_reaches_only_the_function_call_route(tokendb) -> None:
    service = bootstrap_hosted_service_token(tokendb)
    refused = authenticate_request(_http_request("/v1/auth/browser", service.raw_token))
    assert getattr(refused, "status_code", None) == 403
    assert b"hosted_service_scope" in refused.body
    allowed = authenticate_request(
        _http_request("/v1/functions/call", service.raw_token)
    )
    assert isinstance(allowed, HttpAuthContext)
    human = mint_token(
        tokendb, actor_id=seed_human_actor(tokendb, "member"), name="member"
    )
    assert isinstance(
        authenticate_request(_http_request("/v1/auth/browser", human.raw_token)),
        HttpAuthContext,
    )


def test_named_project_decides_the_org_over_a_payload_org(tokendb) -> None:
    project_org = seed_default_org(tokendb)
    other_org = int(
        tokendb.execute(
            "INSERT INTO organizations (slug, name, created_at) "
            "VALUES ('elsewhere', 'Elsewhere', '2026-01-01T00:00:00Z') RETURNING id"
        ).fetchone()[0]
    )
    request = _dispatch_request(
        1, _LIFECYCLE, {"project": "yoke", "org_id": str(other_org)}
    )
    assert resolve_org_context(tokendb, request) == project_org


@pytest.fixture()
def approvals_conn():
    with decision_request_connection() as value:
        yield value


def _pending(conn, *, expires_at: str, member: int = 2) -> None:
    """Open an approval for ``member``; actor 2 owns a project in org 1."""
    approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id=_AUTH_ID,
        org_id=1,
        state="pending",
        occurred_at="2026-07-28T12:00:00Z",
        actor_id=member,
        context={"expires_at": expires_at},
    )


def _end(conn, *, actor_id: int, state: str = "expired"):
    return approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id=_AUTH_ID,
        org_id=1,
        state=state,
        occurred_at="2099-12-31T00:00:00Z",
        actor_id=actor_id,
        context={},
    )


@pytest.mark.parametrize("state", ("expired", "withdrawn"))
def test_service_cannot_end_a_live_machine_approval(approvals_conn, state) -> None:
    """The delivery's own claimed status and occurred_at prove nothing."""
    _pending(approvals_conn, expires_at="2099-01-01T00:00:00Z")
    with pytest.raises(PermissionError, match="hosted_service_withdrawal_subject_live"):
        _end(approvals_conn, actor_id=6, state=state)
    status = approvals_conn.execute("SELECT status FROM decision_requests").fetchone()[
        0
    ]
    assert status == "pending"


@pytest.mark.parametrize(
    "departure",
    (
        "UPDATE actors SET status = 'disabled' WHERE id = 2",
        "DELETE FROM actor_project_roles WHERE actor_id = 2",
    ),
)
def test_service_ends_a_live_approval_whose_member_left_the_org(
    approvals_conn, departure
) -> None:
    """The member's own rows, not the delivery, show the subject ended."""
    _pending(approvals_conn, expires_at="2099-01-01T00:00:00Z")
    approvals_conn.execute(departure)
    withdrawn, _, applied = _end(approvals_conn, actor_id=6, state="withdrawn")
    assert withdrawn is not None
    assert (withdrawn["status"], applied) == ("withdrawn", True)


def test_disabled_service_actor_cannot_end_a_machine_approval(approvals_conn) -> None:
    _pending(approvals_conn, expires_at="2026-07-28T12:10:00Z")
    approvals_conn.execute("UPDATE actors SET status = 'disabled' WHERE id = 6")
    with pytest.raises(PermissionError):
        _end(approvals_conn, actor_id=6)


def test_another_orgs_service_actor_cannot_end_a_machine_approval(
    approvals_conn,
) -> None:
    _pending(approvals_conn, expires_at="2026-07-28T12:10:00Z")
    approvals_conn.execute(
        "INSERT INTO organizations VALUES (2, 'elsewhere', 'Elsewhere', 'now')"
    )
    approvals_conn.execute("UPDATE actor_org_roles SET org_id = 2 WHERE actor_id = 6")
    with pytest.raises(PermissionError, match="not authorized"):
        _end(approvals_conn, actor_id=6)


@pytest.mark.parametrize(
    ("actor_id", "kind", "component"),
    ((1, "human", None), (7, "system", "some_other_component")),
)
def test_non_service_role_holder_cannot_end_a_machine_approval(
    approvals_conn, actor_id, kind, component
) -> None:
    _pending(approvals_conn, expires_at="2026-07-28T12:10:00Z")
    if actor_id == 7:
        approvals_conn.execute(
            "INSERT INTO actors (id, kind, system_component, created_at) "
            "VALUES (7, ?, ?, 'now')",
            (kind, component),
        )
    approvals_conn.execute(
        "INSERT INTO actor_org_roles VALUES (?, 1, 5, 'now')", (actor_id,)
    )
    with pytest.raises(PermissionError, match="not authorized"):
        _end(approvals_conn, actor_id=actor_id)

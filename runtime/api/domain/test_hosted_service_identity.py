"""The hosted service calls a universe as its own least-privilege identity."""

from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.api.routes.functions import _service_token_guard_response
from yoke_core.domain import api_tokens_cli, json_helper
from yoke_core.domain import machine_approval_requests as approvals
from yoke_core.domain.actor_permissions import (
    PERM_HOSTED_SERVICE_DELIVER,
    PERM_PROJECT_ADMIN,
    ROLE_HOSTED_SERVICE,
    grant_actor_org_role,
    grant_actor_project_role,
    org_permission_decision,
    permission_decision,
    seed_roles_and_permissions,
)
from yoke_core.domain.api_tokens import (
    INITIAL_ADMIN_TOKEN_NAME,
    bootstrap_admin_token,
    bootstrap_hosted_service_token,
    verify_token,
)
from yoke_core.domain.function_authz_scope import ORG, classify, permission_key_for
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.hosted_service_authority import (
    HOSTED_SERVICE_COMPONENT,
    hosted_service_org_ids,
)
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

_LIFECYCLE = "projects.github_binding.lifecycle"


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


def _guard(conn, actor_id: int, token_name: str):
    return _service_token_guard_response(
        {"function": _LIFECYCLE, "version": "v1", "request_id": "delivery-1"},
        lookup(_LIFECYCLE),
        HttpAuthContext(token_id=1, actor_id=actor_id, token_name=token_name),
        conn=conn,
    )


def test_mint_converges_one_system_actor_with_one_org_grant(tokendb) -> None:
    first = bootstrap_hosted_service_token(tokendb)
    second = bootstrap_hosted_service_token(tokendb)

    assert second.actor_id == first.actor_id
    assert second.token_id != first.token_id
    assert verify_token(tokendb, first.raw_token).actor_id == first.actor_id
    assert verify_token(tokendb, second.raw_token).actor_id == first.actor_id
    actor = tokendb.execute(
        "SELECT kind, system_component FROM actors WHERE id = %s",
        (first.actor_id,),
    ).fetchone()
    assert tuple(actor) == ("system", HOSTED_SERVICE_COMPONENT)
    grants = tokendb.execute(
        "SELECT aor.org_id, r.name FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id WHERE aor.actor_id = %s",
        (first.actor_id,),
    ).fetchall()
    assert [tuple(row) for row in grants] == [
        (seed_default_org(tokendb), ROLE_HOSTED_SERVICE)
    ]
    project_grants = tokendb.execute(
        "SELECT COUNT(*) FROM actor_project_roles WHERE actor_id = %s",
        (first.actor_id,),
    ).fetchone()[0]
    assert project_grants == 0


def test_mint_refuses_an_identity_carrying_broader_authority(tokendb) -> None:
    created = bootstrap_hosted_service_token(tokendb)
    grant_actor_project_role(
        tokendb,
        actor_id=created.actor_id,
        project_id=resolve_project_id(tokendb, "yoke"),
        role_name="viewer",
    )
    with pytest.raises(ValueError, match="hosted_service_identity_not_least_privilege"):
        bootstrap_hosted_service_token(tokendb)


def test_cli_mints_the_hosted_service_token(tokendb, capsys) -> None:
    assert api_tokens_cli.main(["hosted-service"]) == 0
    body = json_helper.loads_text(capsys.readouterr().out)
    verified = verify_token(tokendb, body["raw_token"])
    assert verified.actor_id == body["actor_id"]
    assert verified.name == "hosted-service"
    assert hosted_service_org_ids(tokendb, body["actor_id"])


def test_org_admin_carries_no_service_only_permission(tokendb) -> None:
    admin = bootstrap_admin_token(tokendb)
    org_id = seed_default_org(tokendb)
    project_id = resolve_project_id(tokendb, "yoke")

    assert not org_permission_decision(
        tokendb,
        actor_id=admin.actor_id,
        org_id=org_id,
        permission_key=PERM_HOSTED_SERVICE_DELIVER,
    ).allowed
    assert not permission_decision(
        tokendb,
        actor_id=admin.actor_id,
        project_id=project_id,
        permission_key=PERM_HOSTED_SERVICE_DELIVER,
    ).allowed
    # The admin wildcard still carries ordinary permissions.
    assert permission_decision(
        tokendb,
        actor_id=admin.actor_id,
        project_id=project_id,
        permission_key=PERM_PROJECT_ADMIN,
    ).allowed
    assert hosted_service_org_ids(tokendb, admin.actor_id) == frozenset()


def test_member_grant_surfaces_cannot_hand_out_the_service_role(tokendb) -> None:
    admin = bootstrap_admin_token(tokendb)
    with pytest.raises(ValueError, match="role_not_grantable_at_org_scope"):
        grant_actor_org_role(
            tokendb,
            actor_id=admin.actor_id,
            org_id=seed_default_org(tokendb),
            role_name=ROLE_HOSTED_SERVICE,
        )


def test_guard_recognizes_the_identity_not_the_token_name(tokendb, registry) -> None:
    admin = bootstrap_admin_token(tokendb)
    service = bootstrap_hosted_service_token(tokendb)

    denial = _guard(tokendb, admin.actor_id, INITIAL_ADMIN_TOKEN_NAME)
    assert denial is not None
    assert denial.error is not None
    assert denial.error.code == "permission_denied"
    assert "hosted service identity" in denial.error.message
    assert "api_tokens_cli hosted-service" in denial.error.message

    assert _guard(tokendb, service.actor_id, "any-name") is None


def test_lifecycle_dispatch_authority_is_the_service_permission(registry) -> None:
    entry = lookup(_LIFECYCLE)
    assert "service_token_required" in entry.guardrails
    spec = classify(
        entry.function_id,
        side_effects=bool(entry.side_effects),
        project_permission=permission_key_for(entry),
    )
    assert (spec.scope, spec.permission_key) == (ORG, PERM_HOSTED_SERVICE_DELIVER)


def test_guard_ignores_functions_without_the_service_guardrail(registry) -> None:
    entry = lookup("projects.github_binding.bind")
    assert (
        _service_token_guard_response(
            {"function": "projects.github_binding.bind"},
            entry,
            HttpAuthContext(token_id=1, actor_id=1, token_name="doorman:user-7"),
            conn=object(),
        )
        is None
    )


@pytest.fixture()
def approvals_conn():
    with decision_request_connection() as value:
        yield value


def _pending(conn) -> None:
    approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state="pending",
        occurred_at="2026-07-28T12:00:00Z",
        actor_id=6,
        context={"expires_at": "2026-07-28T12:10:00Z"},
    )


@pytest.mark.parametrize("state", ("expired", "withdrawn"))
def test_service_identity_ends_machine_approval_without_org_admin(
    approvals_conn, state
) -> None:
    _pending(approvals_conn)
    withdrawn, _, applied = approvals.apply_machine_approval_lifecycle(
        approvals_conn,
        auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
        org_id=1,
        state=state,
        occurred_at="2026-07-28T12:05:00Z",
        actor_id=6,
        context={},
        reason=f"authorization {state}",
    )
    assert withdrawn is not None
    assert (withdrawn["status"], applied) == ("withdrawn", True)
    actors = approvals_conn.execute(
        "SELECT actor_id FROM events WHERE event_name = 'DecisionRequestWithdrawn'"
    ).fetchall()
    assert [row[0] for row in actors] == [6]


@pytest.mark.parametrize("state", ("approved", "denied"))
def test_service_identity_cannot_decide_a_machine_approval(
    approvals_conn, state
) -> None:
    _pending(approvals_conn)
    with pytest.raises(PermissionError):
        approvals.apply_machine_approval_lifecycle(
            approvals_conn,
            auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
            org_id=1,
            state=state,
            occurred_at="2026-07-28T12:05:00Z",
            actor_id=6,
            context={},
        )


def test_member_without_admin_still_cannot_end_machine_approval(
    approvals_conn,
) -> None:
    _pending(approvals_conn)
    with pytest.raises(PermissionError, match="not authorized"):
        approvals.apply_machine_approval_lifecycle(
            approvals_conn,
            auth_request_id="5b234860-c927-46ab-b19a-9fb36df056aa",
            org_id=1,
            state="expired",
            occurred_at="2026-07-28T12:05:00Z",
            actor_id=1,
            context={},
        )

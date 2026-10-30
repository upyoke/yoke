"""Binding inventory returns authorized data and refuses cross-org callers."""
from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.api.routes.functions import _service_token_guard_response
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.api_tokens import bootstrap_admin_token, bootstrap_hosted_service_token
from yoke_core.domain.github_app_user_verification import VerifiedProjectGitHubBinding
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_github_binding import cmd_bind_project_repo, cmd_unbind_project_repo
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

FUNCTION = "projects.github_binding.list"


@pytest.fixture
def inventory(test_db):
    seed_project_identities(test_db)
    seed_roles_and_permissions(test_db)
    admin = bootstrap_admin_token(test_db)
    service = bootstrap_hosted_service_token(test_db)
    other_org = test_db.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('other', 'Other', '2026-01-01T00:00:00Z') RETURNING id"
    ).fetchone()[0]
    test_db.execute("UPDATE projects SET org_id=%s WHERE slug='externalwebapp'", (other_org,))
    test_db.commit()
    for project, installation, repository in [("yoke", "77", "88"), ("externalwebapp", "99", "66")]:
        verified = VerifiedProjectGitHubBinding(
            installation_id=installation, account_id="10", account_login="example",
            account_type="Organization", repository_selection="selected",
            permissions={}, repository_id=repository, github_repo=f"example/{project}",
            default_branch="main", repository_is_private=True, installation_status="active",
        )
        cmd_bind_project_repo(
            project, installation_id=installation, repository_id=repository,
            github_repo=verified.github_repo, expected_api_url="https://api.github.com",
            github_user_access_token="transient", verifier=lambda **kw: verified,
        )
    reset_registry_for_tests()
    register_all_handlers()
    try:
        yield test_db, service.actor_id, other_org, admin.actor_id
    finally:
        reset_registry_for_tests()


def read(actor, payload=None):
    return dispatch(FunctionCallRequest(
        function=FUNCTION, target=TargetRef(kind="global"),
        actor=ActorContext(actor_id=str(actor), session_id="inventory-reader"),
        payload=payload or {},
    ))


def test_inventory_returns_only_own_org_and_installation_filter(inventory):
    conn, actor, _, _ = inventory
    expected = [{
        "project_id": resolve_project_id(conn, "yoke"), "project": "yoke",
        "installation_id": "77", "repository_id": "88",
        "github_repo": "example/yoke", "api_url": "https://api.github.com",
    }]
    result = read(actor)
    assert result.success, result.error
    assert result.result["rows"] == expected
    assert read(actor, {"installation_id": "77"}).result["rows"] == expected
    assert read(actor, {"installation_id": "99"}).result["rows"] == []
    cmd_unbind_project_repo("yoke")
    assert read(actor).result["rows"] == []


def test_inventory_refuses_foreign_org(inventory):
    _, actor, other_org, _ = inventory
    result = read(actor, {"org_id": other_org})
    assert not result.success
    assert result.error.code == "permission_denied"
    assert "hosted_service.deliver" in result.error.message


def test_inventory_rejects_admin_and_requires_service_token(inventory):
    conn, _, _, admin_actor = inventory
    result = read(admin_actor)
    assert not result.success
    assert result.error.code == "permission_denied"
    entry = lookup(FUNCTION)
    assert entry.minimum_serving_version == "next-release"
    assert entry.adapter_status == "internal"
    denial = _service_token_guard_response(
        {"function": FUNCTION}, entry,
        HttpAuthContext(token_id=1, actor_id=admin_actor, token_name="admin"), conn=conn,
    )
    assert denial.error.code == "permission_denied"

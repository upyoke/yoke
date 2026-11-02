"""Hosted binding authority is checked before GitHub access or persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.domain.test_project_github_binding import _verified
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.api import app_factory
from yoke_core.api.http_auth import HttpAuthContext
from yoke_core.api.routes import functions
from yoke_core.domain import project_github_binding
from yoke_core.domain.api_tokens import bootstrap_hosted_service_token
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests

FUNCTION = "projects.github_binding.bind"


@pytest.fixture()
def binding_db(test_db, monkeypatch):
    seed_project_identities(test_db)
    auth = mint_api_auth_context(test_db, project="externalwebapp")
    test_db.commit()
    reset_registry_for_tests()
    register_all_handlers()
    monkeypatch.setattr(
        project_github_binding, "verify_project_github_binding", lambda **_: _verified()
    )
    try:
        yield test_db, auth
    finally:
        reset_registry_for_tests()


def _request(actor_id, **payload):
    return FunctionCallRequest(
        function=FUNCTION,
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload={
            "project": "externalwebapp",
            "installation_id": "12345",
            "repository_id": "4567",
            "github_repo": "Example-Org/ExternalWebapp",
            "expected_api_url": "https://api.github.com",
            "github_user_access_token": "transient-user-token",
            **payload,
        },
    )


@pytest.mark.parametrize("machine_id", (None, "connected-machine"))
def test_hosted_http_refuses_member_and_machine_before_github(
    binding_db, monkeypatch, machine_id
):
    conn, member = binding_db
    service = bootstrap_hosted_service_token(conn)
    conn.commit()
    monkeypatch.setattr(
        functions,
        "require_auth_context",
        lambda _: HttpAuthContext(
            token_id=member.token.token_id,
            actor_id=member.actor_id,
            token_name="hosted-service",
            machine_id=machine_id,
        ),
    )

    def forbidden(**_):
        pytest.fail("refused bind must not contact GitHub")

    monkeypatch.setattr(project_github_binding, "verify_project_github_binding", forbidden)
    with TestClient(app_factory.create_app()) as client:
        response = client.post(
            "/v1/functions/call",
            headers=member.headers,
            json=_request(service.actor_id).model_dump(),
        )
    body = response.json()
    assert response.status_code == 403
    assert not body["success"]
    assert body["error"]["code"] == "github_binding_hosted_only"
    assert "Connect GitHub" in body["error"]["message"]
    assert "CLI routes automatically" in body["error"]["message"]
    assert conn.execute("SELECT COUNT(*) FROM project_github_repo_bindings").fetchone()[0] == 0


def test_hosted_http_service_can_bind_with_only_its_org_role(binding_db):
    conn, _ = binding_db
    service = bootstrap_hosted_service_token(conn)
    conn.commit()
    with TestClient(app_factory.create_app()) as client:
        response = client.post(
            "/v1/functions/call",
            headers={"Authorization": f"Bearer {service.raw_token}"},
            json=_request(service.actor_id).model_dump(),
        )
    assert response.status_code == 200, response.json()
    assert response.json()["result"]["bound"] is True
    assert conn.execute(
        "SELECT installation_id FROM project_github_repo_bindings WHERE project_id = %s",
        (resolve_project_id(conn, "externalwebapp"),),
    ).fetchone()[0] == "12345"


def test_standalone_member_keeps_project_admin_binding(binding_db):
    conn, member = binding_db
    with TestClient(app_factory.create_app()) as client:
        response = client.post(
            "/v1/functions/call", headers=member.headers,
            json=_request(member.actor_id).model_dump(),
        )
    assert response.status_code == 200, response.json()
    assert response.json()["result"]["bound"] is True
    assert conn.execute("SELECT COUNT(*) FROM project_github_repo_bindings").fetchone()[0] == 1


def test_hosted_service_cannot_bind_another_org_using_target_or_payload_org(binding_db):
    conn, member = binding_db
    service = bootstrap_hosted_service_token(conn)
    other_org = conn.execute(
        "INSERT INTO organizations (slug, name, created_at) "
        "VALUES ('elsewhere', 'Elsewhere', '2026-01-01T00:00:00Z') RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "UPDATE projects SET org_id = %s WHERE slug = 'externalwebapp'", (other_org,)
    )
    request = _request(service.actor_id, org_id=str(member.org_id))
    request.target.project_id = resolve_project_id(conn, "yoke")
    permission = check_dispatch_permission(conn, lookup(FUNCTION), request)
    assert permission.error.error.code == "github_binding_hosted_only"
    assert conn.execute("SELECT COUNT(*) FROM project_github_repo_bindings").fetchone()[0] == 0


@pytest.mark.parametrize("disabled", (False, True))
def test_hosted_identity_without_authority_does_not_reopen_member_binding(
    binding_db, disabled
):
    conn, member = binding_db
    service = bootstrap_hosted_service_token(conn)
    if disabled:
        conn.execute("UPDATE actors SET status = 'disabled' WHERE id = %s", (service.actor_id,))
    else:
        conn.execute("DELETE FROM actor_org_roles WHERE actor_id = %s", (service.actor_id,))
    permission = check_dispatch_permission(conn, lookup(FUNCTION), _request(member.actor_id))
    assert permission.error.error.code == "github_binding_hosted_only"
    service_permission = check_dispatch_permission(conn, lookup(FUNCTION), _request(service.actor_id))
    assert service_permission.error is not None


def test_hosted_service_missing_project_names_target_recovery(binding_db):
    conn, _ = binding_db
    service = bootstrap_hosted_service_token(conn)
    permission = check_dispatch_permission(
        conn, lookup(FUNCTION), _request(service.actor_id, project="absent-project")
    )
    assert permission.error.error.code == "target_not_found"
    assert "existing project by its numeric id" in permission.error.error.message

"""Real-token function authorization boundaries for deployment CI."""

from __future__ import annotations

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.project_identity import resolve_project_id
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)


@pytest.fixture()
def ci_auth_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(ci_auth_db):
    with _client_for_db(ci_auth_db["db_path"]) as authed:
        yield authed


def _deployment_ci_headers(
    db_path: str,
    *,
    project: str = "yoke",
) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=resolve_project_id(conn, project),
            role_name=ROLE_DEPLOYMENT_CI,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name="function-test-deployment-ci")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def _envelope(
    function_id: str,
    *,
    project: str = "yoke",
    payload: dict | None = None,
) -> dict:
    return {
        "function": function_id,
        "actor": {"actor_id": "spoofed", "session_id": "deployment-ci-test"},
        "target": {"kind": "global", "project_id": project},
        "payload": payload if payload is not None else {"project": project},
    }


@pytest.mark.parametrize(
    ("function_id", "payload"),
    [
        ("project.snapshot.sync", {"project_id": "1", "snapshots": []}),
        ("onboard.checklist.init", {"project_id": 1}),
        ("onboard.checklist.run", {"project_id": 1}),
        ("projects.update", {"slug": "yoke", "name": "Yoke"}),
    ],
)
def test_deployment_ci_denies_install_onboarding_and_project_admin_mutations(
    client,
    ci_auth_db,
    function_id,
    payload,
) -> None:
    headers = _deployment_ci_headers(ci_auth_db["db_path"])

    response = client.post(
        "/v1/functions/call",
        json=_envelope(function_id, payload=payload),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize(
    ("function_id", "operation_payload"),
    [
        (
            "github_actions.workflow.dispatch",
            {
                "repo": "example-org/externalwebapp",
                "workflow": "deploy.yml",
                "ref": "main",
                "inputs": {},
                "correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
            },
        ),
        (
            "github_actions.workflow.dispatch_once",
            {
                "repo": "example-org/externalwebapp",
                "workflow": "deploy.yml",
                "ref": "main",
                "inputs": {},
            },
        ),
        (
            "github_actions.workflow.find_run",
            {
                "repo": "example-org/externalwebapp",
                "workflow": "deploy.yml",
                "head_sha": "abc123",
            },
        ),
        (
            "github_actions.run.jobs_count",
            {
                "repo": "example-org/externalwebapp",
                "run_id": "123",
                "attempt": 1,
            },
        ),
        (
            "github_actions.wait_run",
            {"repo": "example-org/externalwebapp", "run_id": "123"},
        ),
        (
            "github_actions.check_ci",
            {
                "repo": "example-org/externalwebapp",
                "workflow": "ci.yml",
                "branch": "main",
            },
        ),
        (
            "github_actions.variable.get",
            {"repo": "example-org/externalwebapp", "name": "YOKE_CI_ENABLED"},
        ),
    ],
)
def test_deployment_ci_target_cannot_override_relay_payload_project(
    client,
    ci_auth_db,
    function_id,
    operation_payload,
) -> None:
    conn = connect_test_db(ci_auth_db["db_path"])
    try:
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, public_item_prefix, created_at) "
            "VALUES (3, 'platform', 'Platform', 'PLT', "
            "'2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()
    headers = _deployment_ci_headers(
        ci_auth_db["db_path"],
        project="platform",
    )
    payload = {"project": "externalwebapp", **operation_payload}

    response = client.post(
        "/v1/functions/call",
        json=_envelope(
            function_id,
            project="platform",
            payload=payload,
        ),
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"

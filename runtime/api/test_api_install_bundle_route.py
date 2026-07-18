"""Route test for ``GET /v1/projects/{id}/install-bundle`` (auth-gated)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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


@pytest.fixture()
def bundle_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(bundle_db):
    with _client_for_db(bundle_db["db_path"]) as authed:
        yield authed


def _deployment_ci_token_headers(db_path: str) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=1,
            role_name=ROLE_DEPLOYMENT_CI,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name="bundle-test-deployment-ci")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_install_bundle_serves_files_and_hooks(client) -> None:
    response = client.get("/v1/projects/2/install-bundle")

    assert response.status_code == 200
    bundle = response.json()
    assert bundle["bundle_schema"] == 1
    assert bundle["project_id"] == 2
    assert bundle["project_slug"] == "externalwebapp"
    paths = [entry["path"] for entry in bundle["files"]]
    assert paths == sorted(paths)
    assert any(p.startswith(".agents/skills/yoke/") for p in paths)
    assert any(p.startswith(".claude/skills/yoke/") for p in paths)
    assert any(p.startswith(".codex/skills/yoke/") for p in paths)
    assert ".agents/skills/yoke/idea/SKILL.md" in paths
    # The full operating layer ships: lifecycle skills + rendered subagents.
    assert ".claude/skills/yoke/conduct/SKILL.md" in paths
    assert ".codex/skills/yoke/shepherd/SKILL.md" in paths
    assert ".claude/agents/yoke-engineer.md" in paths
    assert ".codex/agents/yoke-tester.toml" in paths
    assert ".claude/skills/yoke/onboard-project/SKILL.md" in paths
    assert ".codex/skills/yoke/onboard-project/SKILL.md" in paths
    assert bundle["hooks"]["claude_settings_hooks"]
    assert bundle["hooks"]["codex_hooks"]
    contract = bundle["project_contract_files"]
    assert contract, "bundle must carry the seed-if-missing project contract"
    contract_paths = [entry["path"] for entry in contract]
    assert all(p.startswith(".yoke/") for p in contract_paths)
    assert ".yoke/board.json" in contract_paths
    assert ".yoke/lint-config" in contract_paths
    assert all(entry["install_policy"] == "seed_if_missing" for entry in contract)


def test_install_bundle_unknown_project_is_typed_404(client) -> None:
    response = client.get("/v1/projects/999/install-bundle")

    assert response.status_code == 404
    detail = response.json()["error"]
    assert detail["code"] == "NOT_FOUND"
    assert "999" in detail["message"]


def test_install_bundle_renderer_error_is_typed_500(client, monkeypatch) -> None:
    from yoke_core.api.routes import install as route
    from yoke_core.domain.install_bundle import InstallBundleError

    def _raise_bundle_error(project_id, conn):
        raise InstallBundleError("claude rules source dir is missing")

    monkeypatch.setattr(route, "build_bundle", _raise_bundle_error)

    response = client.get("/v1/projects/2/install-bundle")

    assert response.status_code == 500
    detail = response.json()["error"]
    assert detail["code"] == "INSTALL_BUNDLE_ERROR"
    assert "claude rules source dir is missing" in detail["message"]


def test_install_bundle_requires_auth(client) -> None:
    response = client.get(
        "/v1/projects/2/install-bundle",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("project_id", [1, 2])
def test_deployment_ci_cannot_build_same_or_cross_project_install_bundle(
    client,
    bundle_db,
    monkeypatch,
    project_id,
) -> None:
    from yoke_core.api.routes import install as route

    monkeypatch.setattr(
        route,
        "build_bundle",
        lambda *_args, **_kwargs: pytest.fail("install bundle built before auth"),
    )
    headers = _deployment_ci_token_headers(bundle_db["db_path"])

    response = client.get(
        f"/v1/projects/{project_id}/install-bundle",
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"

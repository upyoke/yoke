"""Route tests for ``GET /v1/projects/{project}/pulumi-stack-config``.

Real minted bearer tokens through the real FastAPI app: 200 with a
``project.install`` grant, 401 without authentication, 403 for an
authenticated actor lacking the grant, 404 for an unknown project, and
payload determinism (the CI consumer renders from this byte-for-byte).
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from yoke_core.domain import db_backend
from yoke_core.domain.actor_permissions import (
    ROLE_VIEWER,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from runtime.api.fixtures.file_test_db import connect_test_db


@pytest.fixture()
def config_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(config_db):
    with _client_for_db(config_db["db_path"]) as authed:
        conn = connect_test_db(config_db["db_path"])
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                "INSERT INTO project_capabilities "
                "(id, project_id, type, settings, created_at) "
                f"VALUES ({p}, {p}, {p}, {p}, {p})",
                (
                    901,
                    1,
                    "github",
                    '{"repo_owner": "acme-org", "repo_name": "acme"}',
                    "2026-06-01T00:00:00Z",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        yield authed


def _bare_token_headers(db_path: str) -> dict[str, str]:
    """Mint a real token for a fresh actor that holds NO roles."""
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        token = mint_token(conn, actor_id=actor_id, name="ci-test-ungranted")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def _viewer_token_headers(db_path: str) -> dict[str, str]:
    """Mint a real token for a fresh actor granted only project viewer."""
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=1,
            role_name=ROLE_VIEWER,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name="ci-test-viewer")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_stack_config_serves_deterministic_snapshot(client) -> None:
    first = client.get("/v1/projects/yoke/pulumi-stack-config")
    second = client.get("/v1/projects/yoke/pulumi-stack-config")

    assert first.status_code == 200
    assert first.json() == second.json()
    payload = first.json()
    assert payload["config_schema"] == 1
    assert payload["project_id"] == 1
    assert payload["project_slug"] == "yoke"
    snapshot = payload["renderer_settings"]
    assert snapshot["project"] == "yoke"
    assert snapshot["capabilities"]["github"]["repo_name"] == "acme"
    assert isinstance(snapshot["environments"], list)


def test_stack_config_numeric_id_matches_slug(client) -> None:
    by_slug = client.get("/v1/projects/yoke/pulumi-stack-config")
    by_id = client.get("/v1/projects/1/pulumi-stack-config")

    assert by_id.status_code == 200
    assert by_id.json() == by_slug.json()


def test_stack_config_requires_auth(client) -> None:
    response = client.get(
        "/v1/projects/yoke/pulumi-stack-config",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_stack_config_denies_actor_without_grant(client, config_db) -> None:
    headers = _bare_token_headers(config_db["db_path"])

    response = client.get(
        "/v1/projects/yoke/pulumi-stack-config", headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_stack_config_denies_viewer_role(client, config_db) -> None:
    """Viewer carries items.read but NOT project.install."""
    headers = _viewer_token_headers(config_db["db_path"])

    response = client.get(
        "/v1/projects/yoke/pulumi-stack-config", headers=headers,
    )

    assert response.status_code == 403


def test_stack_config_unknown_project_is_typed_404(client) -> None:
    response = client.get("/v1/projects/999/pulumi-stack-config")

    assert response.status_code == 404
    detail = response.json()["error"]
    assert detail["code"] == "NOT_FOUND"

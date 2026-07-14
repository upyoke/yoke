"""Route tests for ``GET /v1/templates`` + ``GET /v1/templates/{name}`` (auth-gated)."""

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
from yoke_contracts.template_bundle import (
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_PRODUCT,
    TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token


@pytest.fixture()
def templates_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(templates_db):
    with _client_for_db(templates_db["db_path"]) as authed:
        yield authed


def _bare_token_headers(db_path: str) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        token = mint_token(conn, actor_id=actor_id, name="template-test-bare")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_templates_list_serves_discovered_templates(client) -> None:
    response = client.get("/v1/templates")

    assert response.status_code == 200
    listing = response.json()["templates"]
    by_name = {entry["name"]: entry for entry in listing}
    assert "webapp" in by_name
    assert by_name["webapp"]["description"]  # from templates/webapp/template.json
    assert by_name["webapp"][TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
        TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
    )
    assert by_name["webapp"]["file_count"] > 0
    names = [entry["name"] for entry in listing]
    assert names == sorted(names)


def test_template_bundle_serves_product_webapp_by_default(client) -> None:
    response = client.get("/v1/templates/webapp")

    assert response.status_code == 200
    bundle = response.json()
    assert bundle["template"] == "webapp"
    assert bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
        TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
    )


def test_template_bundle_serves_sorted_raw_files(client) -> None:
    response = client.get("/v1/templates/webapp")

    assert response.status_code == 200
    bundle = response.json()
    assert bundle["bundle_schema"] == 1
    assert bundle["template"] == "webapp"
    assert bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
        TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
    )
    paths = [entry["path"] for entry in bundle["files"]]
    assert paths == sorted(paths)
    assert "template.json" in paths
    assert any(p.startswith("ops/") for p in paths)
    assert all(isinstance(entry["content"], str) for entry in bundle["files"])


def test_source_dev_admin_opt_in_requires_org_admin(
    client, templates_db
) -> None:
    route = f"/v1/templates/webapp?{TEMPLATE_SOURCE_DEV_ADMIN_QUERY_PARAM}=true"
    response = client.get(route, headers=_bare_token_headers(templates_db["db_path"]))

    assert response.status_code == 403
    detail = response.json()["error"]
    assert detail["code"] == "permission_denied"
    assert "org.admin" in detail["message"]


def test_template_bundle_unknown_name_is_typed_404(client) -> None:
    response = client.get("/v1/templates/definitely-not-a-template")

    assert response.status_code == 404
    detail = response.json()["error"]
    assert detail["code"] == "NOT_FOUND"
    assert "definitely-not-a-template" in detail["message"]


def test_template_bundle_is_deterministic(client) -> None:
    route = "/v1/templates/webapp"
    first = client.get(route)
    second = client.get(route)

    assert first.status_code == second.status_code == 200
    assert first.content == second.content


def test_templates_routes_require_auth(client) -> None:
    bad_headers = {"Authorization": "Bearer not-a-real-token"}

    assert client.get("/v1/templates", headers=bad_headers).status_code == 401
    assert client.get(
        "/v1/templates/webapp", headers=bad_headers
    ).status_code == 401

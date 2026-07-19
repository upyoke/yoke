"""Route test for ``GET /v1/cli/manifest`` (auth-gated grammar manifest)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from yoke_cli.manifest import MANIFEST_VERSION

@pytest.fixture()
def manifest_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(manifest_db):
    with _client_for_db(manifest_db["db_path"]) as authed:
        yield authed


def test_manifest_serves_registry_grammar(client) -> None:
    response = client.get("/v1/cli/manifest")

    assert response.status_code == 200
    manifest = response.json()
    assert manifest["manifest_version"] == MANIFEST_VERSION
    rows = manifest["subcommands"]
    assert rows
    assert all(row["tokens"] and row["function_id"] for row in rows)
    by_id = {row["function_id"]: row for row in rows}
    assert by_id["status.run"]["tokens"] == ["status"]
    assert by_id["env.use.run"]["usage"].startswith("yoke env use")


def test_manifest_requires_auth(client) -> None:
    response = client.get(
        "/v1/cli/manifest",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401

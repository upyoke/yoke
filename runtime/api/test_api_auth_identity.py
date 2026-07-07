"""Integration coverage for the authenticated identity summary route."""

from __future__ import annotations

import tempfile
from contextlib import ExitStack
from pathlib import Path

from fastapi.testclient import TestClient

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL, apply_fixture_ddl
from runtime.api.test_api_helpers import _install_overrides
from yoke_core.api.main import app
from yoke_core.domain.actors import set_actor_label


def test_auth_identity_returns_actor_org_roles_and_visible_projects() -> None:
    with ExitStack() as stack:
        tmp_dir = stack.enter_context(tempfile.TemporaryDirectory())
        db_path = stack.enter_context(
            init_test_db(
                Path(tmp_dir),
                apply_schema=lambda: _apply_fixture_ddl_from_active_db(),
            )
        )
        stack.enter_context(_install_overrides(db_path))
        conn = connect_test_db(db_path)
        try:
            auth = mint_api_auth_context(conn)
            set_actor_label(conn, auth.actor_id, "ben")
        finally:
            conn.close()
        client = stack.enter_context(TestClient(app))

        response = client.get("/v1/auth/identity", headers=auth.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["actor"]["id"] == auth.actor_id
    assert body["actor"]["label"] == "ben"
    assert body["token"]["name"] == "test-api-token"
    assert body["orgs"][0]["roles"] == ["admin"]
    projects = {row["slug"]: row for row in body["projects"]}
    assert "yoke" in projects
    assert {"admin", "owner"} <= set(projects["yoke"]["roles"])


def _apply_fixture_ddl_from_active_db() -> None:
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, SCHEMA_DDL)
    finally:
        conn.close()

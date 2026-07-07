"""Route tests for ``POST /v1/db/read``."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.db_read_constants import DB_READ_FUNCTION_ID
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


@pytest.fixture()
def db_read_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(db_read_db):
    reset_registry_for_tests()
    with patch.object(events_module, "emit_event"):
        with patch.object(dispatch_module, "_idempotency_lookup", return_value=None):
            with _client_for_db(db_read_db["db_path"]) as authed:
                yield authed
    reset_registry_for_tests()


def _bare_token_headers(db_path: str) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        token = mint_token(conn, actor_id=actor_id, name="db-read-ungranted")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_db_read_route_returns_bounded_rows(client) -> None:
    response = client.post(
        "/v1/db/read",
        json={"sql": "SELECT id, title FROM items ORDER BY id", "row_cap": 2},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["function"] == DB_READ_FUNCTION_ID
    result = body["result"]
    assert result["columns"] == ["id", "title"]
    assert result["rows"] == [[1, "First item"], [2, "Second item"]]
    assert result["row_count"] == 2
    assert result["row_cap"] == 2
    assert result["truncated"] is True


def test_db_read_route_refuses_write_sql(client) -> None:
    response = client.post(
        "/v1/db/read",
        json={"sql": "UPDATE items SET title = 'x' WHERE id = 1"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "sql_write_refused"


def test_db_read_route_requires_auth(client) -> None:
    response = client.post(
        "/v1/db/read",
        json={"sql": "SELECT 1"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_db_read_route_denies_actor_without_raw_permission(client, db_read_db) -> None:
    response = client.post(
        "/v1/db/read",
        json={"sql": "SELECT 1"},
        headers=_bare_token_headers(db_read_db["db_path"]),
    )

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "permission_denied"

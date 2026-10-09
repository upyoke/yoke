"""POST /v1/items/{public_ref}/capability tests (TestConfigureCapability)."""

from __future__ import annotations

import os
import sys

import pytest

from yoke_contracts.timestamps import parse_instant, format_instant

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    make_client_fixture,
    make_test_db_fixture,
)


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestConfigureCapability:
    def test_create_capability(self, client, test_db):
        resp = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "github",
                "config": {"token": "ghs_test_token_value", "repo": "test"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "yoke"
        assert data["type"] == "github"
        assert data["config"]["token"] == "ghs_test_token_value"
        assert "id" in data
        assert data["created_at"] == format_instant(parse_instant(data["created_at"]))
        assert data["verified_at"] is None

    def test_update_capability_upsert(self, client, test_db):
        # Create first
        resp1 = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "ci",
                "config": {"runner": "local"},
            },
        )
        assert resp1.status_code == 201

        # Update (same project + type)
        resp2 = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "ci",
                "config": {"runner": "remote"},
            },
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["config"]["runner"] == "remote"

    def test_capability_item_not_found(self, client):
        resp = client.post(
            "/v1/items/YOK-999/capability",
            json={
                "type": "github",
                "config": {"key": "value"},
            },
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"

    def test_capability_empty_type(self, client):
        resp = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "",
                "config": {"key": "value"},
            },
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "type" in data["error"]["message"].lower()

    def test_capability_empty_config(self, client):
        resp = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "github",
                "config": {},
            },
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "config" in data["error"]["message"].lower()

    def test_capability_resolves_project_from_item(self, client, test_db):
        # Item 3 has project='externalwebapp'
        resp = client.post(
            "/v1/items/EXT-3/capability",
            json={
                "type": "deploy",
                "config": {"target": "stage"},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "externalwebapp"

    def test_missing_item_project_refuses_before_capability_write(
        self, client, monkeypatch
    ):
        from unittest.mock import Mock
        from yoke_core.api.routes import items_capability

        conn = Mock()
        conn.execute.return_value.fetchone.return_value = {"id": 1, "project_id": None}
        monkeypatch.setattr(items_capability._main, "get_db_readwrite", lambda: conn)
        monkeypatch.setattr(items_capability, "_p", lambda _conn: "%s")
        monkeypatch.setattr(items_capability, "resolve_http_item", lambda *_args: 1)
        monkeypatch.setattr(
            "yoke_core.domain.project_selection.missing_project_on_connection",
            lambda _conn, **_kwargs: (
                "no project given — pass --project P. Accessible projects: accessible."
            ),
        )
        response = client.post(
            "/v1/items/YOK-1/capability",
            json={
                "type": "ci",
                "config": {"runner": "local"},
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "project_required"
        assert "Accessible projects: accessible." in response.json()["error"]["message"]
        conn.execute.assert_called_once()
        conn.commit.assert_not_called()

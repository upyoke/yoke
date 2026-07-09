"""POST /v1/items/{id}/capability tests (TestConfigureCapability)."""

from __future__ import annotations

import os
import sys

import pytest

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
        resp = client.post("/v1/items/1/capability", json={
            "type": "github",
            "config": {"token": "ghs_test_token_value", "repo": "test"},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "yoke"
        assert data["type"] == "github"
        assert data["config"]["token"] == "ghs_test_token_value"
        assert "id" in data
        assert "created_at" in data

    def test_update_capability_upsert(self, client, test_db):
        # Create first
        resp1 = client.post("/v1/items/1/capability", json={
            "type": "ci",
            "config": {"runner": "local"},
        })
        assert resp1.status_code == 201

        # Update (same project + type)
        resp2 = client.post("/v1/items/1/capability", json={
            "type": "ci",
            "config": {"runner": "remote"},
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["config"]["runner"] == "remote"

    def test_capability_item_not_found(self, client):
        resp = client.post("/v1/items/999/capability", json={
            "type": "github",
            "config": {"key": "value"},
        })
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"

    def test_capability_empty_type(self, client):
        resp = client.post("/v1/items/1/capability", json={
            "type": "",
            "config": {"key": "value"},
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "type" in data["error"]["message"].lower()

    def test_capability_empty_config(self, client):
        resp = client.post("/v1/items/1/capability", json={
            "type": "github",
            "config": {},
        })
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "config" in data["error"]["message"].lower()

    def test_capability_resolves_project_from_item(self, client, test_db):
        # Item 3 has project='buzz'
        resp = client.post("/v1/items/3/capability", json={
            "type": "deploy",
            "config": {"target": "staging"},
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["project"] == "buzz"

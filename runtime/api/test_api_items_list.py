"""GET /v1/items list-endpoint tests (TestListItems)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _startup_test_db,
    _startup_error_for_db,
    connect_test_db,
    make_client_fixture,
    make_test_db_fixture,
)


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestListItems:
    def test_list_all_items(self, client):
        resp = client.get("/v1/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 5
        assert len(data["items"]) == 5

    def test_filter_by_status(self, client):
        resp = client.get("/v1/items", params={"status": "implementing"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["title"] == "First item"

    def test_filter_by_project(self, client):
        resp = client.get("/v1/items", params={"project": "buzz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["title"] == "Buzz item"

    def test_filter_by_status_and_project(self, client):
        resp = client.get("/v1/items", params={"status": "idea", "project": "buzz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_filter_no_results(self, client):
        resp = client.get("/v1/items", params={"status": "implementing", "project": "buzz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_invalid_status_returns_400(self, client):
        resp = client.get("/v1/items", params={"status": "bogus"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "bogus" in data["error"]["message"]

    def test_items_exclude_body(self, client):
        """body column removed; list responses should not include body."""
        resp = client.get("/v1/items")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item.get("body") is None

    def test_retired_alias_qa_rejected(self, client):
        """?status=qa is rejected (retired alias)."""
        resp = client.get("/v1/items", params={"status": "qa"})
        assert resp.status_code == 400

    def test_retired_alias_merged_rejected(self, client):
        """?status=merged is rejected (retired alias)."""
        resp = client.get("/v1/items", params={"status": "merged"})
        assert resp.status_code == 400

    def test_startup_rejects_legacy_status_merged(self, tmp_path):
        """startup refuses to serve when retired 'merged' status remains in DB."""
        with _startup_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority, project_id,
                    project_sequence, created_at, updated_at, source)
                   VALUES (99, 'Legacy merged item', 'issue', 'merged',
                           'medium', 1, 99, '2026-03-09T00:00:00Z',
                           '2026-03-09T00:00:00Z', 'user')"""
            )
            conn.commit()
            conn.close()
            message = _startup_error_for_db(db_path)
            assert "retired statuses" in message
            assert "YOK-99=merged" in message
            assert "zero-legacy DB convergence" in message

"""GET /v1/items/{id} single-item tests (TestGetItem)."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    _p,
    _startup_test_db,
    _startup_error_for_db,
    connect_test_db,
    make_client_fixture,
    make_test_db_fixture,
)
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE


@pytest.fixture()
def test_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(test_db):
    yield from make_client_fixture()


class TestGetItem:
    def test_get_existing_item(self, client):
        resp = client.get("/v1/items/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 1
        assert data["title"] == "First item"
        assert data["type"] == "issue"
        assert data["status"] == "implementing"
        assert data["priority"] == "high"
        # body column removed; single-item response returns None
        assert data["body"] is None

    def test_get_item_body_is_none_after_column_removal(self, client):
        """body column removed; single-item response still includes body key (None)."""
        resp = client.get("/v1/items/1")
        assert resp.status_code == 200
        data = resp.json()
        assert "body" in data
        assert data["body"] is None

    def test_get_item_not_found(self, client):
        resp = client.get("/v1/items/999")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "NOT_FOUND"
        assert "999" in data["error"]["message"]

    def test_get_item_frozen_as_bool(self, client):
        resp = client.get("/v1/items/1")
        data = resp.json()
        assert data["frozen"] is False

    def test_startup_rejects_legacy_status_qa(self, tmp_path):
        """startup refuses to serve when retired 'qa' status remains in DB."""
        with _startup_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority, project_id,
                    project_sequence, created_at, updated_at, source)
                   VALUES (98, 'Legacy qa item', 'issue', 'qa', 'medium',
                           1, 98, '2026-03-09T00:00:00Z',
                           '2026-03-09T00:00:00Z', 'user')"""
            )
            conn.commit()
            conn.close()
            message = _startup_error_for_db(db_path)
            assert "retired statuses" in message
            assert "YOK-98=qa" in message
            assert "zero-legacy DB convergence" in message

    def test_startup_accepts_current_lifecycle_statuses(self, tmp_path):
        """Current issue/epic lifecycle statuses boot the API cleanly."""
        with _startup_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            p = _p(conn)
            sql = (
                f"""INSERT INTO items
                   (id, title, type, status, priority, project_id,
                    project_sequence, created_at, updated_at, source)
                   VALUES ({p}, {p}, {p}, {p}, 'medium', 1, {p},
                           '2026-04-05T00:00:00Z',
                           '2026-04-05T00:00:00Z', 'user')"""
            )
            for row in [
                (90, "Epic planning", "epic", "planning", 90),
                (91, "Epic plan refinement", "epic", "refining-plan", 91),
                (92, "Epic review", "epic", "reviewing-implementation", 92),
                (93, "Issue review complete", "issue", "reviewed-implementation", 93),
                (94, "Issue polish", "issue", "polishing-implementation", 94),
                (95, "Issue implemented", "issue", "implemented", 95),
            ]:
                conn.execute(sql, row)
            conn.commit()
            conn.close()

            with _client_for_db(db_path) as client:
                resp = client.get("/v1/health")
                assert resp.status_code == 200

    def test_startup_rejects_missing_strategy_docs_table(self, tmp_path):
        """startup refuses to serve if the install-bundle strategy substrate is absent."""
        with _startup_test_db(tmp_path) as db_path:
            conn = connect_test_db(db_path)
            conn.execute(f"DROP TABLE {STRATEGY_DOCS_TABLE}")
            conn.commit()
            conn.close()

            message = _startup_error_for_db(db_path)

            assert "missing required table" in message
            assert STRATEGY_DOCS_TABLE in message
            assert "yoke_core.domain.schema init" in message

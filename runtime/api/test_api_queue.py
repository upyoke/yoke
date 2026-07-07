"""Queue-filter tests for yoke_core.api.main.

Covers the ``exclude_done``, ``exclude_cancelled``, ``exclude_frozen``, and
``frozen`` query parameters on ``GET /v1/items``.
"""

from __future__ import annotations

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_api_helpers import test_db, client  # noqa: F401


class TestQueueFiltering:
    """Test the exclude_done, exclude_cancelled, exclude_frozen, and frozen
    query parameters added to GET /v1/items for active-queue analysis."""

    def test_exclude_done(self, client):
        """exclude_done=true removes done items from the result."""
        resp = client.get("/v1/items", params={"exclude_done": True})
        assert resp.status_code == 200
        data = resp.json()
        statuses = [i["status"] for i in data["items"]]
        assert "done" not in statuses
        # Item 2 is done — should be excluded
        ids = [i["id"] for i in data["items"]]
        assert 2 not in ids

    def test_exclude_cancelled(self, client):
        """exclude_cancelled=true removes cancelled items from the result."""
        resp = client.get("/v1/items", params={"exclude_cancelled": True})
        assert resp.status_code == 200
        data = resp.json()
        statuses = [i["status"] for i in data["items"]]
        assert "cancelled" not in statuses
        # Item 5 is cancelled — should be excluded
        ids = [i["id"] for i in data["items"]]
        assert 5 not in ids

    def test_exclude_done_and_cancelled(self, client):
        """Both exclusions combine with AND."""
        resp = client.get("/v1/items", params={
            "exclude_done": True,
            "exclude_cancelled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        statuses = [i["status"] for i in data["items"]]
        assert "done" not in statuses
        assert "cancelled" not in statuses

    def test_exclude_frozen(self, client, test_db):
        """exclude_frozen=true removes frozen items."""
        # Add a frozen item
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, frozen, created_at, updated_at, source)
               VALUES (50, 'Frozen item', 'issue', 'implementing', 'medium', 1, 50, 1,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        # Without exclusion — frozen item present
        resp1 = client.get("/v1/items")
        assert resp1.status_code == 200
        ids1 = [i["id"] for i in resp1.json()["items"]]
        assert 50 in ids1

        # With exclusion — frozen item gone
        resp2 = client.get("/v1/items", params={"exclude_frozen": True})
        assert resp2.status_code == 200
        ids2 = [i["id"] for i in resp2.json()["items"]]
        assert 50 not in ids2

    def test_frozen_filter_true(self, client, test_db):
        """frozen=true returns only frozen items."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, frozen, created_at, updated_at, source)
               VALUES (51, 'Another frozen', 'issue', 'idea', 'low', 1, 51, 1,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/items", params={"frozen": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        for item in data["items"]:
            assert item["frozen"] is True

    def test_frozen_filter_false(self, client, test_db):
        """frozen=false returns only non-frozen items."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, frozen, created_at, updated_at, source)
               VALUES (52, 'Yet another frozen', 'issue', 'idea', 'low', 1, 52, 1,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/items", params={"frozen": False})
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["frozen"] is False

    def test_active_queue_combination(self, client):
        """Full active-queue filter: exclude_done + exclude_cancelled + exclude_frozen."""
        resp = client.get("/v1/items", params={
            "exclude_done": True,
            "exclude_cancelled": True,
            "exclude_frozen": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] not in ("done", "cancelled")
            assert item["frozen"] is False

    def test_queue_filters_combine_with_status(self, client):
        """Status filter works alongside queue exclusion filters."""
        resp = client.get("/v1/items", params={
            "status": "implementing",
            "exclude_frozen": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "implementing"
            assert item["frozen"] is False

    def test_queue_filters_combine_with_project(self, client):
        """Project filter works alongside queue exclusion filters."""
        resp = client.get("/v1/items", params={
            "project": "yoke",
            "exclude_done": True,
            "exclude_cancelled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["project"] == "yoke"
            assert item["status"] not in ("done", "cancelled")

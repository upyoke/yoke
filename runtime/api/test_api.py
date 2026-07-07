"""Smoke tests and residual API tests for yoke_core.api.main.

Item CRUD tests -> test_api_items_*
Session tests -> test_api_sessions.py
Deploy/frontier tests -> test_api_deploy.py
Board + domain delegation tests -> test_api_board.py
Queue filtering tests -> test_api_queue.py
Shared schemas + fixtures -> test_api_helpers.py
"""

from __future__ import annotations

import yoke_core.api.main as api_main
from runtime.api.test_api_helpers import test_db, client  # noqa: F401


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_200(self, client, test_db):
        resp = client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "v1"
        assert "db_path" not in data

    def test_health_serves_baked_build_sha(self, client, test_db, monkeypatch):
        """`build` mirrors YOKE_BUILD_SHA (baked at image build) so
        callers can confirm WHICH code is answering; empty when the
        runtime was not image-built."""
        monkeypatch.setenv("YOKE_BUILD_SHA", "abc123def456")
        assert client.get("/v1/health").json()["build"] == "abc123def456"
        monkeypatch.delenv("YOKE_BUILD_SHA")
        assert client.get("/v1/health").json()["build"] == ""


# ---------------------------------------------------------------------------
# Error response envelope structure tests
# ---------------------------------------------------------------------------


class TestErrorEnvelope:
    """Verify all error responses use nested envelope: error.code, error.message."""

    def test_404_envelope(self, client):
        resp = client.get("/v1/items/999")
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        # Must NOT have flat code/message
        assert "code" not in {k for k in data if k != "error"}
        assert "message" not in {k for k in data if k != "error"}

    def test_400_envelope(self, client):
        resp = client.get("/v1/items", params={"status": "invalid"})
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_422_envelope(self, client):
        resp = client.post("/v1/items", json={"title": "", "type": "issue"})
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_409_envelope(self, client):
        resp = client.post("/v1/items/1/approve", json={})
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_STATE"


# ---------------------------------------------------------------------------
# Canonical vocabulary alignment tests
# ---------------------------------------------------------------------------


class TestCanonicalVocabulary:
    """Verify API constants match the canonical delivery lifecycle registry."""

    def test_valid_statuses_no_retired_terms(self):
        """AC-1: VALID_STATUSES must not contain retired terms."""
        from yoke_core.api.main import VALID_STATUSES
        assert "merged" not in VALID_STATUSES
        assert "qa" not in VALID_STATUSES
        assert "validation" not in VALID_STATUSES
        assert "in_release" not in VALID_STATUSES

    def test_valid_statuses_includes_canonical_terms(self):
        """AC-2: VALID_STATUSES must include all canonical delivery statuses."""
        from yoke_core.api.main import VALID_STATUSES
        for status in [
            "refined-idea",
            "implementing",
            "reviewing-implementation",
            "implemented",
            "planning",
            "release",
            "blocked",
            "stopped",
            "failed",
        ]:
            assert status in VALID_STATUSES, f"Missing canonical status: {status}"

    def test_board_column_order_no_retired_terms(self):
        """AC-7: Board columns must not include retired terms."""
        from yoke_core.api.main import BOARD_COLUMN_ORDER
        assert "merged" not in BOARD_COLUMN_ORDER
        assert "qa" not in BOARD_COLUMN_ORDER

    def test_board_column_order_matches_canonical(self):
        """AC-7: Board column order matches STATUS_BOARD_ORDER."""
        from yoke_core.api.main import BOARD_COLUMN_ORDER
        expected = ["idea", "planning", "refined", "implementing", "blocked", "reviewing", "implemented", "release", "done"]
        assert BOARD_COLUMN_ORDER == expected


# ---------------------------------------------------------------------------
# DB helper unit tests
# ---------------------------------------------------------------------------


class TestDBHelpers:
    def test_get_db_path_uses_env(self, test_db):
        import yoke_core.api.main as mod
        path = mod.get_db_path()
        assert path == test_db["db_path"]

    def test_readonly_reads_seeded_authority(self, test_db):
        conn = api_main.get_db_readonly()
        try:
            row = conn.execute("SELECT title FROM items WHERE id = 1").fetchone()
        finally:
            conn.close()
        assert row["title"] == "First item"

    def test_readwrite_allows_writes(self, test_db):
        conn = api_main.get_db_readwrite()
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id,
                project_sequence, created_at, updated_at, source)
               VALUES (999, 'test', 'issue', 'idea', 'low', 1, 999,
                       '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        row = conn.execute("SELECT * FROM items WHERE id = 999").fetchone()
        assert row is not None
        conn.close()

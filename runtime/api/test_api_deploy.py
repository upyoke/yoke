"""Deploy/charge-frontier tests extracted from test_api.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yoke_core.api.main import app
from runtime.api.test_api_deploy_test_helpers import (
    frontier_db,  # noqa: F401 — re-exported pytest fixture
)


# ---------------------------------------------------------------------------
# Charge frontier endpoint tests
# ---------------------------------------------------------------------------


class TestChargeFrontierEndpoint:
    """Tests for GET /v1/charge/frontier."""

    @pytest.fixture(autouse=True)
    def setup_client(self, frontier_db):
        self.client = TestClient(app)
        self.client.headers.update(frontier_db["auth_headers"])
        self.db_info = frontier_db

    def test_frontier_returns_valid_json(self):
        """AC-1: GET /v1/charge/frontier returns valid JSON with correct structure."""
        resp = self.client.get("/v1/charge/frontier")
        assert resp.status_code == 200
        data = resp.json()
        assert "runnable" in data
        assert "blocked" in data
        assert "frozen" in data
        assert "wip_cap" in data
        assert "wip_active" in data
        assert "conduct_eligible" in data
        # Verify we got the expected items (yoke project by default)
        runnable_ids = [item["item_id"] for item in data["runnable"]]
        assert "YOK-20" in runnable_ids
        assert "YOK-21" in runnable_ids
        assert "YOK-26" in runnable_ids
        # should be blocked
        blocked_ids = [item["item_id"] for item in data["blocked"]]
        assert "YOK-22" in blocked_ids
        assert "YOK-27" in blocked_ids
        # done items should not appear anywhere
        all_ids = runnable_ids + blocked_ids + [i["item_id"] for i in data["frozen"]]
        assert "YOK-23" not in all_ids
        # buzz-project items should not appear (default project=yoke)
        assert "YOK-24" not in all_ids

    def test_frontier_project_filter(self):
        """AC-2: Project filter correctly scopes results."""
        resp = self.client.get("/v1/charge/frontier?project=buzz")
        assert resp.status_code == 200
        data = resp.json()
        runnable_ids = [item["item_id"] for item in data["runnable"]]
        assert "YOK-24" in runnable_ids
        # Yoke items should not appear
        assert "YOK-20" not in runnable_ids
        assert "YOK-21" not in runnable_ids

    def test_frontier_wip_cap_override(self):
        """AC-3: WIP cap parameter overrides default."""
        resp = self.client.get("/v1/charge/frontier?wip_cap=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["wip_cap"] == 1
        # With wip_cap=1, only 0 conduct-eligible slots (1 already active)
        # so conduct_eligible may be empty
        assert len(data["conduct_eligible"]) <= 1

    def test_frontier_item_has_all_fields(self):
        """AC-6: Pydantic model fields match FrontierItem dataclass fields 1:1."""
        resp = self.client.get("/v1/charge/frontier")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runnable"]) > 0
        item = data["runnable"][0]
        expected_fields = {
            "item_id", "title", "status", "priority", "project",
            "item_type", "adapter", "blocked_by", "blocked_reasons",
            "unblocks_count", "downstream_depth", "created_at",
        }
        assert set(item.keys()) == expected_fields

    def test_frontier_blocked_item_has_reasons(self):
        """Blocked items include blocked_by and blocked_reasons."""
        resp = self.client.get("/v1/charge/frontier")
        assert resp.status_code == 200
        data = resp.json()
        blocked = data["blocked"]
        assert len(blocked) > 0
        yok22 = [b for b in blocked if b["item_id"] == "YOK-22"]
        assert len(yok22) == 1
        assert "YOK-20" in yok22[0]["blocked_by"]
        assert len(yok22[0]["blocked_reasons"]) > 0

        yok27 = [b for b in blocked if b["item_id"] == "YOK-27"]
        assert len(yok27) == 1
        assert yok27[0]["blocked_by"] == []
        assert any("blocked status" in reason for reason in yok27[0]["blocked_reasons"])

    def test_frontier_frozen_items_separate(self):
        """Frozen items appear in the frozen list, not runnable."""
        resp = self.client.get("/v1/charge/frontier")
        assert resp.status_code == 200
        data = resp.json()
        frozen_ids = [item["item_id"] for item in data["frozen"]]
        assert "YOK-25" in frozen_ids
        runnable_ids = [item["item_id"] for item in data["runnable"]]
        assert "YOK-25" not in runnable_ids

    def test_frontier_invalid_wip_cap(self):
        """AC-5: Invalid wip_cap returns 422."""
        resp = self.client.get("/v1/charge/frontier?wip_cap=0")
        assert resp.status_code == 422
        resp = self.client.get("/v1/charge/frontier?wip_cap=999")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Charge schedule endpoint tests
# ---------------------------------------------------------------------------


class TestChargeScheduleEndpoint:
    """Tests for GET /v1/charge/schedule shared scheduler output."""

    @pytest.fixture(autouse=True)
    def setup_client(self, frontier_db):
        self.client = TestClient(app)
        self.client.headers.update(frontier_db["auth_headers"])
        self.db_info = frontier_db

    def test_schedule_step_has_all_fields(self):
        """Shared scheduler surface exposes downstream_depth on scheduled steps."""
        resp = self.client.get("/v1/charge/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["ranked_steps"]) > 0
        step = data["ranked_steps"][0]
        expected_fields = {
            "item_id", "item_type", "status", "title", "priority",
            "next_step", "rank", "claim_state", "gate_evaluations",
            "explanation", "adapter", "blocked_by", "blocked_reasons",
            "unblocks_count", "downstream_depth", "created_at",
        }
        assert set(step.keys()) == expected_fields

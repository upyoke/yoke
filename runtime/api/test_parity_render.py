# ruff: noqa: F811
"""Parity tests — Group 1: filtered item reads (active queue, status, frozen).
The Group 2 board-projection coverage lives in
:mod:`runtime.api.test_parity_render_board`.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import lifecycle

# parity_env is the backend-aware render-parity fixture: ONE per-test database
# backs BOTH the in-process FastAPI client and the service_client subprocess,
# so parity compares both surfaces against the same Postgres authority.
# _run_service_client spawns that subprocess with the inherited backend env.
from runtime.api.parity_db_router_test_fixtures import (
    parity_env,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_parity import _run_service_client

# ===========================================================================
# Group 1: Filtered item reads — active queue, status filter, frozen filter
# ===========================================================================


class TestActiveQueueParity:
    """Verify API and CLI return the same active-queue results."""

    def test_active_queue_matches_api_exclude_done_cancelled_frozen(self, parity_env):
        """Both surfaces should return the same set of non-done, non-cancelled,
        non-frozen items."""
        db_path = parity_env["db_path"]
        client = parity_env["client"]

        # API: use exclude_done + exclude_cancelled + exclude_frozen
        api_resp = client.get(
            "/v1/items",
            params={
                "exclude_done": True,
                "exclude_cancelled": True,
                "exclude_frozen": True,
            },
        )
        assert api_resp.status_code == 200
        api_ids = sorted(item["id"] for item in api_resp.json()["items"])

        # CLI: active-queue (default filter)
        result = _run_service_client(db_path, "active-queue")
        assert result.returncode == 0
        cli_ids = sorted(
            int(line.split("|")[0])
            for line in result.stdout.strip().split("\n")
            if line.strip()
        )

        assert api_ids == cli_ids, (
            f"API returned {api_ids} but CLI returned {cli_ids}"
        )

        # Verify expected: items 1 (implementing), 3 (idea/externalwebapp), 4 (release),
        # 7 (reviewing-implementation), 8 (implemented), 9 (blocked)
        # are active queue.
        # Items excluded: 2 (done), 5 (cancelled), 6 (frozen)
        assert 2 not in api_ids, "Done item should be excluded"
        assert 5 not in api_ids, "Cancelled item should be excluded"
        assert 6 not in api_ids, "Frozen item should be excluded"
        assert 1 in api_ids, "Implementing item should be included"

    def test_active_queue_project_scoped(self, parity_env):
        """Both surfaces should return the same results when scoped to a project."""
        db_path = parity_env["db_path"]
        client = parity_env["client"]

        # API: project=yoke + exclude filters
        api_resp = client.get(
            "/v1/items",
            params={
                "project": "yoke",
                "exclude_done": True,
                "exclude_cancelled": True,
                "exclude_frozen": True,
            },
        )
        assert api_resp.status_code == 200
        api_ids = sorted(item["id"] for item in api_resp.json()["items"])

        # CLI: active-queue --project yoke
        result = _run_service_client(db_path, "active-queue", "--project", "yoke")
        assert result.returncode == 0
        cli_ids = sorted(
            int(line.split("|")[0])
            for line in result.stdout.strip().split("\n")
            if line.strip()
        )

        assert api_ids == cli_ids
        # Item 3 is externalwebapp, so it should NOT be in yoke-scoped results
        assert 3 not in api_ids


class TestStatusFilterParity:
    """Verify API status filter and domain-layer status validation agree."""

    def test_valid_status_filter_api(self, parity_env):
        """API should return items filtered by a valid status."""
        client = parity_env["client"]
        resp = client.get("/v1/items", params={"status": "implementing"})
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["status"] == "implementing"

    def test_invalid_status_rejected_by_api(self, parity_env):
        """API should reject an invalid status value."""
        client = parity_env["client"]
        resp = client.get("/v1/items", params={"status": "merged"})
        assert resp.status_code == 400
        assert "VALIDATION_ERROR" in resp.json()["error"]["code"]

    def test_validate_status_cli_matches_api_acceptance(self, parity_env):
        """CLI validate-status should agree with API on valid/invalid statuses."""
        db_path = parity_env["db_path"]
        client = parity_env["client"]

        for status in lifecycle.ALL_ITEM_STATUSES:
            # API accepts it
            resp = client.get("/v1/items", params={"status": status})
            assert resp.status_code == 200, f"API rejected valid status '{status}'"
            # CLI accepts it
            result = _run_service_client(db_path, "validate-status", status)
            assert result.returncode == 0, f"CLI rejected valid status '{status}'"

        # Invalid statuses should be rejected by both
        for bad_status in ["merged", "in_progress", "qa", "validation", "in_release"]:
            resp = client.get("/v1/items", params={"status": bad_status})
            assert resp.status_code == 400, f"API accepted invalid status '{bad_status}'"
            result = _run_service_client(db_path, "validate-status", bad_status)
            assert result.returncode == 1, f"CLI accepted invalid status '{bad_status}'"


class TestFrozenFilterParity:
    """Verify API and domain layer agree on frozen semantics."""

    def test_frozen_excluded_by_default_in_active_queue(self, parity_env):
        """Active queue excludes frozen items on both surfaces."""
        db_path = parity_env["db_path"]
        client = parity_env["client"]

        # API with exclude_frozen
        api_resp = client.get(
            "/v1/items",
            params={"exclude_frozen": True},
        )
        api_ids = [item["id"] for item in api_resp.json()["items"]]
        assert 6 not in api_ids, "Frozen item (id=6) should be excluded"

        # CLI active-queue also excludes frozen by default
        result = _run_service_client(db_path, "active-queue")
        assert result.returncode == 0
        cli_ids = [
            int(line.split("|")[0])
            for line in result.stdout.strip().split("\n")
            if line.strip()
        ]
        assert 6 not in cli_ids, "Frozen item (id=6) should be excluded from active-queue"

    def test_frozen_included_when_filter_not_set(self, parity_env):
        """Without exclude_frozen, frozen items appear in API results."""
        client = parity_env["client"]

        resp = client.get("/v1/items")
        assert resp.status_code == 200
        all_ids = [item["id"] for item in resp.json()["items"]]
        assert 6 in all_ids, "Frozen item should appear when not excluded"

    def test_frozen_filter_true_returns_only_frozen(self, parity_env):
        """API frozen=true returns only frozen items."""
        client = parity_env["client"]

        resp = client.get("/v1/items", params={"frozen": True})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == 6
        assert items[0]["frozen"] is True

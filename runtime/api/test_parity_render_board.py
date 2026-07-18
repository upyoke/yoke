"""Parity tests — Group 2: board projection (bucket classification, stats).

Splits the Group 2 board-projection coverage out of
:mod:`runtime.api.test_parity_render`, which keeps Group 1 (filtered
item reads).
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import board
from runtime.api.fixtures.file_test_db import connect_test_db

# parity_env is the backend-aware render-parity fixture: ONE per-test database
# backs BOTH the in-process FastAPI client and the service_client subprocess,
# so parity compares both surfaces against the same Postgres authority.
# _run_service_client spawns that subprocess with the inherited backend env.
from runtime.api.parity_db_router_test_fixtures import (
    parity_env,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_parity import _run_service_client


# ===========================================================================
# Group 2: Board projection — bucket classification, stats
# ===========================================================================


class TestBoardProjectionParity:
    """Verify API board endpoint and CLI classify-status agree on buckets."""

    def test_classify_status_matches_board_bucket_rules(self, parity_env):
        """CLI classify-status should produce the same bucket as the domain layer."""
        db_path = parity_env["db_path"]

        # Test a comprehensive set of status -> bucket mappings
        test_cases = [
            # (status, frozen, has_active_run, expected_bucket)
            ("done", 0, False, "done"),
            ("cancelled", 0, False, "done"),
            ("implementing", 0, False, "implementing"),
            ("reviewing-implementation", 0, False, "reviewing"),
            ("reviewed-implementation", 0, False, "reviewing"),
            ("polishing-implementation", 0, False, "reviewing"),
            ("planned", 0, False, "refined"),
            ("refined-idea", 0, False, "refined"),
            ("idea", 0, False, "idea"),
            ("refining-idea", 0, False, "planning"),
            ("planning", 0, False, "planning"),
            ("implemented", 0, False, "implemented"),
            ("release", 0, False, "release"),
            ("blocked", 0, False, "blocked"),
            ("stopped", 0, False, "blocked"),
            ("failed", 0, False, "blocked"),
            # Frozen override
            ("planned", 1, False, "frozen"),
            ("implementing", 1, False, "frozen"),
            # Frozen does NOT override done/cancelled
            ("done", 1, False, "done"),
            ("cancelled", 1, False, "done"),
            # Active run upgrades implemented -> release
            ("implemented", 0, True, "release"),
        ]

        for status, frozen, has_run, expected in test_cases:
            # Domain layer
            domain_bucket = board.status_to_board_bucket(
                status=status,
                frozen_value=frozen,
                has_active_run=has_run,
            )
            assert domain_bucket == expected, (
                f"Domain: {status}/frozen={frozen}/run={has_run} -> "
                f"{domain_bucket}, expected {expected}"
            )

            # CLI classify-status
            args = ["classify-status", status]
            if frozen:
                args.extend(["--frozen", str(frozen)])
            if has_run:
                args.extend(["--has-active-run", "1"])
            result = _run_service_client(db_path, *args)
            assert result.returncode == 0
            cli_bucket = result.stdout.strip()
            assert cli_bucket == expected, (
                f"CLI: {status}/frozen={frozen}/run={has_run} -> "
                f"{cli_bucket}, expected {expected}"
            )

    def test_board_api_returns_correct_buckets(self, parity_env):
        """Board API endpoint should classify items into correct buckets."""
        client = parity_env["client"]

        resp = client.get("/v1/board", params={"project": "yoke"})
        assert resp.status_code == 200
        data = resp.json()

        assert data["project"] == "yoke"

        columns = data["columns"]
        # Verify expected bucket assignments for yoke project items
        # Item 1: implementing -> implementing bucket
        implementing_ids = [item["id"] for item in columns.get("implementing", [])]
        assert 1 in implementing_ids, "Item 1 (implementing) should be in implementing bucket"

        # Item 2: done -> done bucket
        done_ids = [item["id"] for item in columns.get("done", [])]
        assert 2 in done_ids, "Item 2 (done) should be in done bucket"

        # Item 5: cancelled is excluded from board query
        all_board_ids = []
        for col_items in columns.values():
            all_board_ids.extend(item["id"] for item in col_items)
        assert 5 not in all_board_ids, "Cancelled items excluded from board"

        # Item 6: frozen -> excluded from board display
        assert 6 not in all_board_ids, "Frozen items excluded from board"

        # Item 7: reviewing-implementation -> reviewing bucket
        reviewing_ids = [item["id"] for item in columns.get("reviewing", [])]
        assert 7 in reviewing_ids, "Item 7 (reviewing-implementation) should be in reviewing bucket"

        # Item 8: implemented + active run -> release bucket
        release_ids = [item["id"] for item in columns.get("release", [])]
        implemented_ids = [item["id"] for item in columns.get("implemented", [])]
        assert 8 in release_ids, "Item 8 (implemented + active run) should be in release bucket"
        assert 8 not in implemented_ids, "Item 8 should not remain in implemented bucket"

        # Item 9: blocked -> blocked bucket
        blocked_ids = [item["id"] for item in columns.get("blocked", [])]
        assert 9 in blocked_ids, "Item 9 (blocked) should be in blocked bucket"

    def test_board_api_scopes_items_to_requested_project(self, parity_env):
        """Board should not include items from other projects."""
        client = parity_env["client"]
        db_path = parity_env["db_path"]

        # Insert through the backend factory so the row lands in the same
        # authority the API reads — the per-test Postgres database on Postgres,
        # the active authority -- not a fixture database the API never opens.
        conn = connect_test_db(db_path)
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source, frozen)
               VALUES (10, 'ExternalWebapp implementing item', 'issue', 'implementing', 'medium', 2, 2,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user', 0)"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/board", params={"project": "yoke"})
        assert resp.status_code == 200
        columns = resp.json()["columns"]

        implementing_ids = [item["id"] for item in columns.get("implementing", [])]
        assert 10 not in implementing_ids, "Board should exclude items from other projects"

    def test_board_stats_computation(self, parity_env):
        """Board stats should match domain-layer board projection logic."""
        client = parity_env["client"]

        resp = client.get("/v1/board", params={"project": "yoke"})
        assert resp.status_code == 200
        stats = resp.json()["stats"]

        # Stats should have total, done, active, remaining
        assert stats["total"] > 0
        assert stats["done"] >= 0
        assert stats["active"] >= 0
        assert stats["remaining"] == stats["total"] - stats["done"] - stats["active"]

    def test_board_empty_for_nonexistent_project(self, parity_env):
        """Board should return empty for a project with no items."""
        client = parity_env["client"]

        resp = client.get("/v1/board", params={"project": "nonexistent"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["total"] == 0

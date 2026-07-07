"""Board endpoint tests and domain-delegation tests for yoke_core.api.main.

Covers the ``/v1/board`` response shape and the API's delegation to the
domain layer (lifecycle constants, board bucket mapping, approval flow
resolution).
"""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_api_helpers import test_db, client  # noqa: F401


# ---------------------------------------------------------------------------
# GET /v1/board tests
# ---------------------------------------------------------------------------


class TestBoard:
    def test_board_returns_yoke_scope(self, client):
        resp = client.get("/v1/board")
        assert resp.status_code == 200
        data = resp.json()
        assert "sprint" not in data
        assert data["project"] == "yoke"
        assert "columns" in data
        assert "stats" in data

    def test_board_columns_structure(self, client):
        resp = client.get("/v1/board")
        data = resp.json()
        # Board should have columns matching canonical BOARD_COLUMN_ORDER
        expected_columns = [
            "idea", "planning", "refined", "implementing", "blocked",
            "reviewing", "implemented", "release", "done",
        ]
        assert list(data["columns"].keys()) == expected_columns
        # Retired statuses must NOT appear as board columns
        assert "merged" not in data["columns"]
        assert "qa" not in data["columns"]
        assert "cancelled" not in data["columns"]

    def test_board_stats(self, client):
        resp = client.get("/v1/board")
        data = resp.json()
        stats = data["stats"]
        # yoke project has items 1(implementing), 2(done), 4(release), 5(cancelled)
        # Cancelled items are excluded from board
        assert stats["total"] == 3  # items 1, 2, 4 (not 5/cancelled)
        assert stats["done"] == 1   # item 2
        assert stats["active"] == 1  # response model still exposes the legacy stats field name

    def test_board_items_in_correct_columns(self, client):
        resp = client.get("/v1/board")
        data = resp.json()
        implementing_items = data["columns"]["implementing"]
        assert len(implementing_items) == 1
        assert implementing_items[0]["title"] == "First item"

    def test_board_excludes_cancelled(self, client):
        resp = client.get("/v1/board")
        data = resp.json()
        all_item_titles = []
        for col_items in data["columns"].values():
            for item in col_items:
                all_item_titles.append(item["title"])
        assert "Cancelled item" not in all_item_titles

    def test_board_other_project(self, client):
        resp = client.get("/v1/board", params={"project": "buzz"})
        assert resp.status_code == 200
        data = resp.json()
        assert "sprint" not in data
        # Buzz has 1 item (id=3, status=idea)
        assert data["stats"]["total"] == 1


# ---------------------------------------------------------------------------
# Domain delegation verification tests (task 003)
# ---------------------------------------------------------------------------


class TestDomainDelegation:
    """Verify that API endpoints actually delegate to domain layer modules
    and that domain constants are the source of truth for API constants."""

    def test_valid_statuses_sourced_from_domain(self):
        """VALID_STATUSES in main.py matches domain.lifecycle.ALL_ITEM_STATUSES."""
        from yoke_core.api.main import VALID_STATUSES
        from yoke_core.domain.lifecycle import ALL_ITEM_STATUSES
        assert VALID_STATUSES == list(ALL_ITEM_STATUSES)

    def test_board_column_order_sourced_from_domain(self):
        """BOARD_COLUMN_ORDER in main.py matches domain.lifecycle.BOARD_COLUMN_ORDER."""
        from yoke_core.api.main import BOARD_COLUMN_ORDER
        from yoke_core.domain.lifecycle import BOARD_COLUMN_ORDER as DOMAIN_BCO
        assert BOARD_COLUMN_ORDER == list(DOMAIN_BCO)

    def test_board_uses_domain_bucket_mapping(self, client, test_db):
        """Board groups items by domain bucket rules, not inline status match.

        Items with status 'reviewing-implementation' should appear in the
        'reviewing' bucket, not in a 'reviewing-implementation' column.
        """
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source)
               VALUES (60, 'In review', 'issue', 'reviewing-implementation', 'medium', 1, 60,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/board")
        assert resp.status_code == 200
        data = resp.json()
        reviewing_titles = [i["title"] for i in data["columns"]["reviewing"]]
        assert "In review" in reviewing_titles
        # reviewing-implementation should NOT be a column key
        assert "reviewing-implementation" not in data["columns"]

    def test_board_maps_blocked_statuses(self, client, test_db):
        """stopped and failed map to the blocked bucket per domain rules."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source)
               VALUES (61, 'Stopped item', 'issue', 'stopped', 'medium', 1, 61,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                created_at, updated_at, source)
               VALUES (62, 'Failed item', 'issue', 'failed', 'medium', 1, 62,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/board")
        assert resp.status_code == 200
        data = resp.json()
        blocked_titles = [i["title"] for i in data["columns"]["blocked"]]
        assert "Stopped item" in blocked_titles
        assert "Failed item" in blocked_titles

    def test_board_maps_pipeline_to_refined(self, client, test_db):
        """refined-idea and planned map to the refined bucket."""
        conn = connect_test_db(test_db["db_path"])
        for item_id, status, label in [(63, "refined-idea", "Refined"), (65, "planned", "Planned")]:
            conn.execute(
                f"""INSERT INTO items
                   (id, title, type, status, priority, project_id, project_sequence,
                    created_at, updated_at, source)
                   VALUES ({item_id}, '{label} item', 'issue', '{status}',
                           'medium', 1, {item_id},
                           '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
            )
        conn.commit()
        conn.close()

        resp = client.get("/v1/board")
        assert resp.status_code == 200
        data = resp.json()
        refined_titles = [i["title"] for i in data["columns"]["refined"]]
        assert "Refined item" in refined_titles
        assert "Planned item" in refined_titles

    def test_board_frozen_item_excluded(self, client, test_db):
        """Frozen items are excluded from the board display."""
        conn = connect_test_db(test_db["db_path"])
        conn.execute(
            """INSERT INTO items
               (id, title, type, status, priority, project_id, project_sequence,
                frozen, created_at, updated_at, source)
               VALUES (66, 'Frozen board item', 'issue', 'implementing', 'medium',
                       1, 66, 1,
                       '2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z', 'user')"""
        )
        conn.commit()
        conn.close()

        resp = client.get("/v1/board")
        assert resp.status_code == 200
        data = resp.json()
        all_titles = []
        for items_list in data["columns"].values():
            all_titles.extend(i["title"] for i in items_list)
        assert "Frozen board item" not in all_titles

    def test_approve_uses_domain_approval_resolution(self, client, test_db):
        """Approval endpoint delegates flow-stage validation to domain layer.

        Tests that a stage whose executor is not human-approval is correctly
        rejected by the domain resolve_approval function.
        """
        # Set item to a non-approval stage
        conn = connect_test_db(test_db["db_path"])
        conn.execute("UPDATE items SET deploy_stage = 'merged' WHERE id = 4")
        conn.execute(
            "UPDATE deployment_runs SET current_stage = 'merged' "
            "WHERE id = 'run-20260325-001'"
        )
        conn.commit()
        conn.close()

        resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_STATE"
        # The error should come from the domain layer
        assert "not a human-approval stage" in data["error"]["message"]

    def test_approve_uses_domain_run_lookup(self, client, test_db):
        """Approval endpoint uses domain runs.find_active_run_for_item
        to locate the active run, correctly ignoring terminal runs.
        """
        conn = connect_test_db(test_db["db_path"])
        # Mark the existing run as succeeded (terminal)
        conn.execute(
            "UPDATE deployment_runs SET status = 'succeeded' "
            "WHERE id = 'run-20260325-001'"
        )
        conn.commit()
        conn.close()

        # With no active run, approval should still succeed (fallback path)
        with patch("yoke_core.api.main.subprocess.run"):
            resp = client.post("/v1/items/4/approve", json={})
        assert resp.status_code == 200

        # Verify only the item was updated (not the terminal run)
        conn = connect_test_db(test_db["db_path"])
        run_row = conn.execute(
            "SELECT current_stage, status FROM deployment_runs "
            "WHERE id = 'run-20260325-001'"
        ).fetchone()
        # Run should NOT have been advanced (it was terminal)
        assert run_row["status"] == "succeeded"
        assert run_row["current_stage"] == "approve-deploy"
        conn.close()

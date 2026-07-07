"""AC-2, AC-5, AC-7, AC-9: ``compute_frontier`` end-to-end + edge cases.

Covers TestComputeFrontier (basic partition, hard/integration gates,
project scoping, frozen exclusion) and TestEdgeCases (empty backlog,
all-blocked, multiple-blockers, failed/blocked-status handling).
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier import (
    AdapterCategory,
    FrontierResult,
    compute_frontier,
)
from runtime.api.frontier_test_helpers import (
    insert_dep as _insert_dep,
    insert_item as _insert_item,
    make_test_db as _create_test_db,
)


# ---------------------------------------------------------------------------
# compute_frontier with DB
# ---------------------------------------------------------------------------


class TestComputeFrontier:
    """AC-2, AC-5, AC-7, AC-9: compute_frontier with SQL-based resolution."""

    def test_basic_partition(self):
        """AC-2: Returns FrontierResult with runnable/blocked partitions."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="idea")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert isinstance(result, FrontierResult)
        assert len(result.runnable) == 2
        assert len(result.blocked) == 0

    def test_hard_block_creates_blocked_partition(self):
        """AC-5: Hard-block deps resolved via SQL join."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        # is blocked by an implementing (non-done) item
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.blocked) == 1
        assert result.blocked[0].item_id == "YOK-10"
        assert len(result.runnable) == 1
        assert result.runnable[0].item_id == "YOK-20"

    def test_integration_gate_does_not_block_activation(self):
        """Integration-gate deps do NOT block the activation frontier."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_dep(conn, "YOK-10", "YOK-20", gate_point="integration", satisfaction="fact:merged")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.blocked) == 0
        assert len(result.runnable) == 2

    def test_satisfied_hard_block_not_blocking(self):
        """Hard-block with blocking item done is treated as satisfied."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="done")  # Blocker is done
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        # is done so not in frontier; the dependent item is unblocked
        assert len(result.runnable) == 1
        assert result.runnable[0].item_id == "YOK-10"
        assert len(result.blocked) == 0

    def test_blocked_reasons_human_readable(self):
        """AC-7: Blocked items include human-readable reasons."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = result.blocked[0]
        assert len(blocked.blocked_reasons) == 1
        assert "YOK-20" in blocked.blocked_reasons[0]
        assert "implementing" in blocked.blocked_reasons[0]

    def test_frozen_items_excluded(self):
        """AC-9: Frozen items excluded from runnable frontier."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", frozen=0, item_type="epic")
        _insert_item(conn, 20, status="planned", frozen=1, item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.runnable) == 1
        assert result.runnable[0].item_id == "YOK-10"
        assert len(result.frozen) == 1
        assert result.frozen[0].item_id == "YOK-20"

    def test_done_and_stopped_items_excluded_but_implemented_is_runnable(self):
        """Done/stopped are excluded, while implemented stays on the usher frontier."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="done")
        _insert_item(conn, 30, status="stopped")
        _insert_item(conn, 40, status="implemented")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        runnable_ids = {item.item_id for item in result.runnable}
        assert runnable_ids == {"YOK-10", "YOK-40"}
        implemented = [item for item in result.runnable if item.item_id == "YOK-40"][0]
        assert implemented.adapter == AdapterCategory.USHER

    def test_project_scoping(self):
        """Only items from the specified project appear."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", project="yoke", item_type="epic")
        _insert_item(conn, 20, status="planned", project="buzz", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.runnable) == 1
        assert result.runnable[0].item_id == "YOK-10"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_backlog(self):
        conn = _create_test_db()
        conn.commit()
        result = compute_frontier(conn, project_scope=["yoke"])
        assert result.runnable == []
        assert result.blocked == []
        assert result.frozen == []

    def test_all_items_blocked(self):
        """All items blocked produces empty runnable, populated blocked."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="planned", item_type="epic")
        # Circular blocker
        _insert_dep(conn, "YOK-10", "YOK-20")
        _insert_dep(conn, "YOK-20", "YOK-10")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.runnable) == 0
        assert len(result.blocked) == 2

    def test_multiple_blockers_on_single_item(self):
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_item(conn, 30, status="implementing")
        _insert_dep(conn, "YOK-10", "YOK-20")
        _insert_dep(conn, "YOK-10", "YOK-30")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = [i for i in result.blocked if i.item_id == "YOK-10"]
        assert len(blocked) == 1
        assert len(blocked[0].blocked_by) == 2
        assert len(blocked[0].blocked_reasons) == 2

    def test_failed_items_excluded_from_frontier(self):
        """Failed items are excluded by the SQL (terminal state)."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="failed")
        _insert_item(conn, 20, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.runnable) == 1
        assert result.runnable[0].item_id == "YOK-20"

    def test_blocked_status_items_go_to_blocked_bucket(self):
        """Explicitly blocked items should never be offered as runnable work."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="blocked")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert result.runnable == []
        assert len(result.blocked) == 1
        assert result.blocked[0].item_id == "YOK-10"
        assert result.blocked[0].adapter == AdapterCategory.WAIT
        assert result.blocked[0].blocked_by == []
        assert "blocked status" in result.blocked[0].blocked_reasons[0]

    def test_single_item_frontier(self):
        """Single-item backlog produces exactly one runnable item."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="idea")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        assert len(result.runnable) == 1
        assert len(result.blocked) == 0
        assert len(result.frozen) == 0

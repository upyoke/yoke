"""AC-4 + AC-6: WIP-cap enforcement and 500-item performance.

Covers TestWipCap (basic cap math, non-conduct items, unblocks_count
population), TestWipCapExtended (large surplus, exactly-full, usher
exemption, review-counts-as-WIP, conduct-eligible rank order), and
TestPerformance (<2s for 500 items + determinism on 500 items).
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain import db_backend
from yoke_core.domain.frontier import (
    AdapterCategory,
    compute_frontier,
)
from runtime.api.frontier_test_helpers import (
    insert_dep as _insert_dep,
    insert_item as _insert_item,
    make_test_db as _create_test_db,
)


# ---------------------------------------------------------------------------
# WIP cap enforcement
# ---------------------------------------------------------------------------


class TestWipCap:
    """AC-6: WIP cap limits conduct-eligible items."""

    def test_wip_cap_limits_conduct_eligible(self):
        conn = _create_test_db()
        # 3 items already implementing (WIP)
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 3, status="implementing")
        # 2 items planned for conduct
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 11, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=4)
        assert result.wip_active == 3
        assert result.wip_cap == 4
        # Only 1 slot remaining (4 - 3 = 1)
        assert len(result.conduct_eligible) == 1

    def test_wip_cap_zero_remaining(self):
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 10, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        assert result.wip_active == 2
        assert len(result.conduct_eligible) == 0
        # But the planned item is still in runnable
        planned_items = [i for i in result.runnable if i.status == "planned"]
        assert len(planned_items) == 1

    def test_non_conduct_items_not_wip_limited(self):
        """Shepherd/refine items are not limited by WIP cap."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 10, status="idea", item_type="epic")  # shepherd
        _insert_item(conn, 11, status="planning", item_type="epic")  # shepherd
        _insert_item(conn, 12, status="idea", item_type="issue")  # refine
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        # Non-conduct items still in runnable even though WIP is full
        non_conduct = [i for i in result.runnable
                       if i.adapter in (AdapterCategory.SHEPHERD, AdapterCategory.REFINE)]
        assert len(non_conduct) == 3

    def test_unblocks_count_populated(self):
        """Items that blocker others get their unblocks_count set."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="implementing")
        _insert_item(conn, 20, status="planned", item_type="epic")
        _insert_item(conn, 30, status="planned", item_type="epic")
        # both blockers still active
        _insert_dep(conn, "YOK-20", "YOK-10")
        _insert_dep(conn, "YOK-30", "YOK-10")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        yok10 = [i for i in result.runnable if i.item_id == "YOK-10"]
        assert len(yok10) == 1
        assert yok10[0].unblocks_count == 2


# ---------------------------------------------------------------------------
# WIP cap enforcement (extended)
# ---------------------------------------------------------------------------


class TestWipCapExtended:
    """AC-4: Additional WIP cap enforcement scenarios."""

    def test_wip_cap_large_surplus(self):
        """When WIP cap far exceeds active items, all conduct items are eligible."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 11, status="planned", item_type="epic")
        _insert_item(conn, 12, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=100)
        assert result.wip_active == 1
        # 4 conduct items: 1 implementing + 3 planned (all fit within wip_cap=100)
        assert len(result.conduct_eligible) == 4

    def test_wip_cap_exactly_full(self):
        """WIP cap exactly equals active count: zero conduct eligible."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 10, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        assert result.wip_active == 2
        assert result.wip_cap == 2
        assert len(result.conduct_eligible) == 0

    def test_usher_items_not_wip_limited(self):
        """Usher items (implemented/release) are not limited by WIP cap."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="implementing")
        _insert_item(conn, 10, status="implemented")
        _insert_item(conn, 11, status="release")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        usher = [i for i in result.runnable if i.adapter == AdapterCategory.USHER]
        assert len(usher) == 2

    def test_review_items_count_as_wip(self):
        """Reviewing-implementation items count toward WIP."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")
        _insert_item(conn, 2, status="reviewing-implementation")
        _insert_item(conn, 10, status="planned", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        assert result.wip_active == 2
        assert len(result.conduct_eligible) == 0

    def test_conduct_eligible_respects_rank_order(self):
        """Conduct-eligible items are returned in rank order, not insertion order."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", priority="low", item_type="epic")
        _insert_item(conn, 11, status="planned", priority="high", item_type="epic")
        _insert_item(conn, 12, status="planned", priority="medium", item_type="epic")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"], wip_cap=2)
        ids = [i.item_id for i in result.conduct_eligible]
        assert ids[0] == "YOK-11"  # high priority first
        assert len(ids) == 2


# ---------------------------------------------------------------------------
# Performance test (backend-aware limit for 500 items)
# ---------------------------------------------------------------------------


class TestPerformance:
    """AC-6: Performance test asserts a backend-appropriate 500-item cap."""

    def test_500_items_under_backend_limit(self):
        """Frontier computation for 500 items stays within the backend cap."""
        import time

        conn = _create_test_db()
        # Insert 500 items with varied statuses
        statuses = [
            "idea", "refining-idea", "refined-idea", "planning", "planned",
            "implementing", "reviewing-implementation", "implemented",
            "release", "blocked",
        ]
        priorities = ["high", "medium", "low"]
        for i in range(1, 501):
            _insert_item(
                conn, i,
                status=statuses[i % len(statuses)],
                priority=priorities[i % len(priorities)],
                created_at=f"2026-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00Z",
            )

        # Add 200 blocker dependencies (varied patterns)
        for i in range(1, 201):
            dep_id = i * 2
            blk_id = i * 2 + 1
            if dep_id <= 500 and blk_id <= 500:
                _insert_dep(conn, f"YOK-{dep_id}", f"YOK-{blk_id}")
        conn.commit()

        start = time.monotonic()
        result = compute_frontier(conn, project_scope=["yoke"])
        elapsed = time.monotonic() - start

        limit = 6.0 if db_backend.connection_is_postgres(conn) else 2.0
        assert elapsed < limit, (
            f"Frontier computation took {elapsed:.3f}s (limit: {limit:.1f}s)"
        )
        # Sanity checks: we got results
        total = len(result.runnable) + len(result.blocked) + len(result.frozen)
        assert total > 0

    def test_500_items_deterministic(self):
        """Repeated runs on 500-item DB produce identical results."""
        conn = _create_test_db()
        statuses = ["idea", "planning", "planned", "implementing", "implemented"]
        for i in range(1, 501):
            _insert_item(
                conn, i,
                status=statuses[i % len(statuses)],
                priority=["high", "medium", "low"][i % 3],
                created_at=f"2026-01-{(i % 28) + 1:02d}T00:00:00Z",
            )
        for i in range(1, 101):
            _insert_dep(conn, f"YOK-{i}", f"YOK-{i + 100}")
        conn.commit()

        result1 = compute_frontier(conn, project_scope=["yoke"])
        result2 = compute_frontier(conn, project_scope=["yoke"])
        ids1 = [i.item_id for i in result1.runnable]
        ids2 = [i.item_id for i in result2.runnable]
        assert ids1 == ids2

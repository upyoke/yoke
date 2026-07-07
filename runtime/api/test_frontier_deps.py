"""AC-3: Blocked-item reporting + transitive dependency resolution.

Covers TestBlockedItemReporting (reason format, multiple blockers,
adapter override to WAIT) and TestTransitiveDependencies (chains, diamond,
chain-resolves-when-head-done).
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
# Blocked-item reporting with dependency reasons (extended)
# ---------------------------------------------------------------------------


class TestBlockedItemReporting:
    """AC-3: Detailed blocked-item reporting with dependency reasons."""

    def test_single_blocker_reason_format(self):
        """Reason string includes blocker ID and its status."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = result.blocked[0]
        assert blocked.item_id == "YOK-10"
        assert len(blocked.blocked_reasons) == 1
        reason = blocked.blocked_reasons[0]
        assert "YOK-20" in reason
        assert "implementing" in reason

    def test_multiple_blockers_all_reasons_present(self):
        """Each blocker generates its own reason string."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_item(conn, 30, status="idea")
        _insert_dep(conn, "YOK-10", "YOK-20")
        _insert_dep(conn, "YOK-10", "YOK-30")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = [i for i in result.blocked if i.item_id == "YOK-10"]
        assert len(blocked) == 1
        reasons = blocked[0].blocked_reasons
        assert len(reasons) == 2
        reason_text = " ".join(reasons)
        assert "YOK-20" in reason_text
        assert "YOK-30" in reason_text

    def test_blocked_by_list_matches_reasons(self):
        """blocked_by IDs correspond 1:1 with blocked_reasons."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="implementing")
        _insert_item(conn, 30, status="reviewing-implementation")
        _insert_dep(conn, "YOK-10", "YOK-20")
        _insert_dep(conn, "YOK-10", "YOK-30")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = [i for i in result.blocked if i.item_id == "YOK-10"][0]
        assert len(blocked.blocked_by) == len(blocked.blocked_reasons)
        for bid, reason in zip(blocked.blocked_by, blocked.blocked_reasons):
            assert bid in reason

    def test_blocker_in_idea_status_shows_idea(self):
        """Reason string reflects the actual status of the blocker."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")
        _insert_item(conn, 20, status="idea")
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        reason = result.blocked[0].blocked_reasons[0]
        assert "idea" in reason

    def test_adapter_overridden_to_wait_for_blocked_items(self):
        """Blocked items have their adapter overridden to WAIT regardless of status."""
        conn = _create_test_db()
        _insert_item(conn, 10, status="planned", item_type="epic")  # Would be CONDUCT
        _insert_item(conn, 20, status="implementing")
        _insert_dep(conn, "YOK-10", "YOK-20")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked = result.blocked[0]
        assert blocked.adapter == AdapterCategory.WAIT


# ---------------------------------------------------------------------------
# Transitive dependency tests
# ---------------------------------------------------------------------------


class TestTransitiveDependencies:
    """Transitive dependency chains and resolution."""

    def test_chain_a_blocks_b_blocks_c(self):
        """A blocks B blocks C: B and C both blocked when A is implementing."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")  # A
        _insert_item(conn, 2, status="planned", item_type="epic")   # B blocked by A
        _insert_item(conn, 3, status="planned", item_type="epic")   # C blocked by B
        _insert_dep(conn, "YOK-2", "YOK-1")
        _insert_dep(conn, "YOK-3", "YOK-2")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked_ids = {i.item_id for i in result.blocked}
        assert "YOK-2" in blocked_ids
        assert "YOK-3" in blocked_ids
        runnable_ids = {i.item_id for i in result.runnable}
        assert "YOK-1" in runnable_ids

    def test_chain_resolves_when_head_done(self):
        """When A (head of chain) is done, B unblocked; C still blocked by B."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="done")    # A done
        _insert_item(conn, 2, status="planned", item_type="epic")   # B was blocked by A, now free
        _insert_item(conn, 3, status="planned", item_type="epic")   # C blocked by B (B not done)
        _insert_dep(conn, "YOK-2", "YOK-1")
        _insert_dep(conn, "YOK-3", "YOK-2")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        runnable_ids = {i.item_id for i in result.runnable}
        blocked_ids = {i.item_id for i in result.blocked}
        assert "YOK-2" in runnable_ids  # A is done, B is free
        assert "YOK-3" in blocked_ids   # B is not done, C still blocked

    def test_diamond_dependency(self):
        """Diamond: D depends on both B and C; B and C depend on A."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="implementing")  # A
        _insert_item(conn, 2, status="planned", item_type="epic")   # B
        _insert_item(conn, 3, status="planned", item_type="epic")   # C
        _insert_item(conn, 4, status="planned", item_type="epic")   # D
        _insert_dep(conn, "YOK-2", "YOK-1")
        _insert_dep(conn, "YOK-3", "YOK-1")
        _insert_dep(conn, "YOK-4", "YOK-2")
        _insert_dep(conn, "YOK-4", "YOK-3")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        blocked_ids = {i.item_id for i in result.blocked}
        assert "YOK-2" in blocked_ids
        assert "YOK-3" in blocked_ids
        assert "YOK-4" in blocked_ids
        runnable_ids = {i.item_id for i in result.runnable}
        assert "YOK-1" in runnable_ids

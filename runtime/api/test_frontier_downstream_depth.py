"""Downstream-depth ranking + FrontierComputed telemetry.

Covers TestDownstreamDepthRanking (depth-beats-breadth, transitive vs depth,
fall-back ordering, cycles, diamond depths, observed-case fixture) and
TestFrontierTelemetry (FrontierComputed event emission with session/project).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier import (
    AdapterCategory,
    FrontierItem,
    compute_frontier,
    rank_frontier,
)
from runtime.api.frontier_test_helpers import (
    insert_dep as _insert_dep,
    insert_item as _insert_item,
    make_test_db as _create_test_db,
)


# ---------------------------------------------------------------------------
# Downstream depth-aware ranking
# ---------------------------------------------------------------------------


class TestDownstreamDepthRanking:
    """Scheduler ranks by critical-path depth, not just fan-out."""

    def _item(self, **kw) -> FrontierItem:
        defaults = dict(
            item_id="YOK-1", title="Test", status="planned",
            priority="medium", project="yoke", item_type="epic",
            adapter=AdapterCategory.CONDUCT, created_at="2026-01-01T00:00:00Z",
        )
        defaults.update(kw)
        return FrontierItem(**defaults)

    def test_depth_beats_breadth_in_ranking(self):
        """AC-depth-aware-ranking: deeper chain outranks shallow broad fan-out.

        Mirrors the observed blocker-chain case:
        - Item A: direct unblocks=2, downstream depth=5 (deep chain)
        - Item B: direct unblocks=7, downstream depth=2 (broad fan-out)
        At same priority, A should rank above B.
        """
        items = [
            self._item(item_id="YOK-B", unblocks_count=7, downstream_depth=2),
            self._item(item_id="YOK-A", unblocks_count=2, downstream_depth=5),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-A", (
            "Deeper downstream chain should outrank broader but shallower fan-out"
        )

    def test_transitive_count_only_does_not_satisfy_observed_case(self):
        """AC-no-transitive-only-regression: transitive reach alone is insufficient.

        If we only used transitive reach (total downstream items reachable):
        - Item A: reach=7
        - Item B: reach=8
        B would outrank A.  But A has depth=5 vs B's depth=2, so A should win.
        This test verifies that depth, not reach, is the deciding factor.
        """
        # Simulate transitive-only: set unblocks_count to transitive reach values
        items = [
            self._item(item_id="YOK-B", unblocks_count=8, downstream_depth=2),
            self._item(item_id="YOK-A", unblocks_count=7, downstream_depth=5),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-A", (
            "Depth must dominate over transitive reach count"
        )

    def test_same_depth_falls_back_to_unblocks(self):
        """Within same depth, higher direct unblocks_count still wins."""
        items = [
            self._item(item_id="YOK-1", downstream_depth=3, unblocks_count=1),
            self._item(item_id="YOK-2", downstream_depth=3, unblocks_count=5),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-2"

    def test_zero_depth_items_sorted_by_unblocks(self):
        """Items with no downstream deps are sorted by direct unblocks_count."""
        items = [
            self._item(item_id="YOK-1", downstream_depth=0, unblocks_count=0),
            self._item(item_id="YOK-2", downstream_depth=0, unblocks_count=3),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-2"

    def test_priority_still_dominates_depth(self):
        """Priority is the top-level sort key, above depth."""
        items = [
            self._item(item_id="YOK-1", priority="medium", downstream_depth=10),
            self._item(item_id="YOK-2", priority="high", downstream_depth=1),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-2"

    def test_downstream_depth_populated_by_compute_frontier(self):
        """AC-derived-metric: compute_frontier sets downstream_depth from dependency graph."""
        conn = _create_test_db()
        # Chain: A -> B -> C -> D
        for i in range(1, 5):
            _insert_item(conn, i, status="idea")
        _insert_dep(conn, "YOK-2", "YOK-1")
        _insert_dep(conn, "YOK-3", "YOK-2")
        _insert_dep(conn, "YOK-4", "YOK-3")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        # is runnable (no blockers);..4 are blocked.
        # Depth is set on all frontier items regardless of partition.
        all_items = result.runnable + result.blocked
        depth_map = {fi.item_id: fi.downstream_depth for fi in all_items}
        assert depth_map.get("YOK-1") == 3, "Head of 4-item chain should have depth 3"
        assert depth_map.get("YOK-4") == 0, "Tail item has no downstream deps"

    def test_unblocks_count_ignores_non_activation_dependencies(self):
        """Activation frontier ranking should ignore integration/closure fan-out."""
        conn = _create_test_db()
        for i in range(1, 6):
            _insert_item(conn, i, status="idea")
        _insert_dep(conn, "YOK-3", "YOK-1", gate_point="activation")
        _insert_dep(conn, "YOK-4", "YOK-2", gate_point="integration")
        _insert_dep(conn, "YOK-5", "YOK-2", gate_point="closure")
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        runnable = {fi.item_id: fi for fi in result.runnable}

        assert runnable["YOK-1"].unblocks_count == 1
        assert runnable["YOK-2"].unblocks_count == 0

    def test_observed_case_fixture(self):
        """AC-validates-observed-case: fixture mirroring the observed blocker-chain graph.

        chain (depth 5): 1221 -> 1227 -> 1185 -> 1186 -> 1188 -> 1189
        fan-out (depth 2): 1233 -> {7 direct leaf deps, some with 1 child}
        Both same priority. 1221 must rank above 1233.
        """
        conn = _create_test_db()

        # All items at same priority, idea status
        all_ids = [1221, 1227, 1185, 1186, 1188, 1189,
                   1233, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008]
        for item_id in all_ids:
            _insert_item(conn, item_id, status="idea", priority="high")

        # deep chain: 1221 -> 1227 -> 1185 -> 1186 -> 1188 -> 1189
        _insert_dep(conn, "YOK-1227", "YOK-1221")
        _insert_dep(conn, "YOK-1185", "YOK-1227")
        _insert_dep(conn, "YOK-1186", "YOK-1185")
        _insert_dep(conn, "YOK-1188", "YOK-1186")
        _insert_dep(conn, "YOK-1189", "YOK-1188")

        # broad fan-out: 7 direct dependents
        for dep_id in [2001, 2002, 2003, 2004, 2005, 2006, 2007]:
            _insert_dep(conn, f"YOK-{dep_id}", "YOK-1233")
        # One of the fan-out items has a child (depth 2 from 1233)
        _insert_dep(conn, "YOK-2008", "YOK-2001")

        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        # Both 1221 and 1233 should be runnable (no unsatisfied blockers on them)
        runnable_ids = [fi.item_id for fi in result.runnable]
        assert "YOK-1221" in runnable_ids
        assert "YOK-1233" in runnable_ids

        # Verify depths
        depth_of = {fi.item_id: fi.downstream_depth for fi in result.runnable}
        assert depth_of["YOK-1221"] == 5, "1221 heads a 5-hop chain"
        assert depth_of["YOK-1233"] == 2, "1233 has depth 2 (fan-out with one child)"

        # Verify ranking: 1221 must come before 1233
        idx_1221 = runnable_ids.index("YOK-1221")
        idx_1233 = runnable_ids.index("YOK-1233")
        assert idx_1221 < idx_1233, (
            f"YOK-1221 (depth=5) must rank above YOK-1233 (depth=2), "
            f"got positions {idx_1221} vs {idx_1233}"
        )

    def test_downstream_depth_handles_cycles(self):
        """Cycles in the dependency graph do not cause infinite recursion."""
        conn = _create_test_db()
        _insert_item(conn, 1, status="idea")
        _insert_item(conn, 2, status="idea")
        _insert_item(conn, 3, status="idea")
        # Cycle: 1 -> 2 -> 3 -> 1
        _insert_dep(conn, "YOK-2", "YOK-1")
        _insert_dep(conn, "YOK-3", "YOK-2")
        _insert_dep(conn, "YOK-1", "YOK-3")
        conn.commit()

        # Should complete without hanging; depths may be imprecise but not crash
        result = compute_frontier(conn, project_scope=["yoke"])
        # All items blocked due to mutual deps — just verify no hang
        total = len(result.runnable) + len(result.blocked)
        assert total > 0

    def test_downstream_depth_diamond(self):
        """Diamond graph: depth is max path, not shortest path."""
        conn = _create_test_db()
        # A -> B -> D (path length 2)
        # A -> C -> E -> D (path length 3)
        # A's depth should be 3 (longest path)
        for i in range(1, 6):
            _insert_item(conn, i, status="idea")
        _insert_dep(conn, "YOK-2", "YOK-1")  # A -> B
        _insert_dep(conn, "YOK-3", "YOK-1")  # A -> C
        _insert_dep(conn, "YOK-4", "YOK-2")  # B -> D
        _insert_dep(conn, "YOK-5", "YOK-3")  # C -> E
        _insert_dep(conn, "YOK-4", "YOK-5")  # E -> D
        conn.commit()

        result = compute_frontier(conn, project_scope=["yoke"])
        depth_of = {fi.item_id: fi.downstream_depth for fi in result.runnable}
        assert depth_of.get("YOK-1") == 3, "Longest path A->C->E->D is 3 hops"


class TestFrontierTelemetry:
    @patch("yoke_core.domain.events.emit_event")
    def test_frontier_computed_carries_session_id_and_project(self, mock_emit):
        conn = _create_test_db()
        _insert_item(conn, 1, status="planned", project="buzz", item_type="epic")

        compute_frontier(conn, project_scope=["buzz"], session_id="sess-frontier")

        frontier_calls = [
            call for call in mock_emit.call_args_list
            if call.args and call.args[0] == "FrontierComputed"
        ]
        assert len(frontier_calls) == 1
        kwargs = frontier_calls[0].kwargs
        assert kwargs["session_id"] == "sess-frontier"
        assert kwargs["project"] == "buzz"
        assert kwargs["context"]["project_scope"] == ["buzz"]

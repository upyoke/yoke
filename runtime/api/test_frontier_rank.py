"""AC-4 + AC-5: Frontier ranking — deterministic ordering and repeatability.

Covers TestRankFrontier (basic priority/unblocks/age/lifecycle ordering) and
TestRankingDeterminism (repeated/reversed/shuffled-input invariance). Both
classes operate on hand-built FrontierItem instances and do not touch the DB.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.frontier import (
    AdapterCategory,
    FrontierItem,
    rank_frontier,
)


# ---------------------------------------------------------------------------
# rank_frontier deterministic ordering
# ---------------------------------------------------------------------------


class TestRankFrontier:
    """AC-4: rank_frontier produces deterministic ordering."""

    def _item(self, **kw) -> FrontierItem:
        defaults = dict(
            item_id="YOK-1", title="Test", status="planned",
            priority="medium", project="yoke", item_type="epic",
            adapter=AdapterCategory.CONDUCT, created_at="2026-01-01T00:00:00Z",
        )
        defaults.update(kw)
        return FrontierItem(**defaults)

    def test_priority_ordering(self):
        items = [
            self._item(item_id="YOK-1", priority="low"),
            self._item(item_id="YOK-2", priority="high"),
            self._item(item_id="YOK-3", priority="medium"),
        ]
        ranked = rank_frontier(items)
        assert [i.item_id for i in ranked] == ["YOK-2", "YOK-3", "YOK-1"]

    def test_unblocking_value(self):
        """Items that unblock more other items rank higher (same priority)."""
        items = [
            self._item(item_id="YOK-1", unblocks_count=0),
            self._item(item_id="YOK-2", unblocks_count=3),
            self._item(item_id="YOK-3", unblocks_count=1),
        ]
        ranked = rank_frontier(items)
        assert [i.item_id for i in ranked] == ["YOK-2", "YOK-3", "YOK-1"]

    def test_lifecycle_stage_prefers_closer_to_done(self):
        """Items closer to done rank higher (same priority, same unblocks).

        Uses epic-progression statuses (idea, implementing, implemented) since
        progression_index() defaults to the epic progression.
        """
        items = [
            self._item(item_id="YOK-1", status="idea", adapter=AdapterCategory.SHEPHERD),
            self._item(item_id="YOK-2", status="implementing", adapter=AdapterCategory.CONDUCT),
            self._item(item_id="YOK-3", status="implemented", adapter=AdapterCategory.USHER),
        ]
        ranked = rank_frontier(items)
        assert [i.item_id for i in ranked] == ["YOK-3", "YOK-2", "YOK-1"]

    def test_age_tiebreaker(self):
        """Older items rank higher when all other criteria are equal."""
        items = [
            self._item(item_id="YOK-3", created_at="2026-03-01T00:00:00Z"),
            self._item(item_id="YOK-1", created_at="2026-01-01T00:00:00Z"),
            self._item(item_id="YOK-2", created_at="2026-02-01T00:00:00Z"),
        ]
        ranked = rank_frontier(items)
        assert [i.item_id for i in ranked] == ["YOK-1", "YOK-2", "YOK-3"]

    def test_deterministic_repeated_calls(self):
        """Multiple calls with same input produce same output."""
        items = [
            self._item(item_id="YOK-1", priority="high", unblocks_count=2),
            self._item(item_id="YOK-2", priority="high", unblocks_count=1),
            self._item(item_id="YOK-3", priority="medium", unblocks_count=5),
        ]
        result1 = rank_frontier(items)
        result2 = rank_frontier(items)
        assert [i.item_id for i in result1] == [i.item_id for i in result2]

    def test_empty_list(self):
        assert rank_frontier([]) == []

    def test_usher_clears_ahead_of_higher_priority_non_usher(self):
        """Ready-to-release work clears before new work regardless of priority.

        A medium-priority ``implemented`` item must outrank a high-priority
        ``refined-idea`` item. Rationale: releasing completed work reduces
        WIP, unblocks downstream dependents, and captures value that is
        already paid for — strictly more valuable than starting new work.
        """
        items = [
            self._item(
                item_id="YOK-high-new",
                priority="high",
                status="refined-idea",
                adapter=AdapterCategory.SHEPHERD,
            ),
            self._item(
                item_id="YOK-med-done",
                priority="medium",
                status="implemented",
                adapter=AdapterCategory.USHER,
            ),
        ]
        ranked = rank_frontier(items)
        assert ranked[0].item_id == "YOK-med-done", (
            "Usher-eligible items must clear ahead of higher-priority non-usher work"
        )

    def test_usher_items_ordered_by_priority_among_themselves(self):
        """Within the usher tier, priority still breaks ties."""
        items = [
            self._item(
                item_id="YOK-med",
                priority="medium",
                status="implemented",
                adapter=AdapterCategory.USHER,
            ),
            self._item(
                item_id="YOK-high",
                priority="high",
                status="implemented",
                adapter=AdapterCategory.USHER,
            ),
        ]
        ranked = rank_frontier(items)
        assert [i.item_id for i in ranked] == ["YOK-high", "YOK-med"]


# ---------------------------------------------------------------------------
# Ranking determinism (extended)
# ---------------------------------------------------------------------------


class TestRankingDeterminism:
    """AC-5: Ranking is deterministic across repeated runs."""

    def _item(self, **kw) -> FrontierItem:
        defaults = dict(
            item_id="YOK-1", title="Test", status="planned",
            priority="medium", project="yoke", item_type="epic",
            adapter=AdapterCategory.CONDUCT, created_at="2026-01-01T00:00:00Z",
        )
        defaults.update(kw)
        return FrontierItem(**defaults)

    def test_ten_repeated_runs_identical(self):
        """10 repeated calls produce identical ordering every time."""
        items = [
            self._item(item_id=f"YOK-{i}", priority=p, unblocks_count=u,
                        created_at=f"2026-01-{i:02d}T00:00:00Z")
            for i, (p, u) in enumerate([
                ("high", 3), ("high", 1), ("medium", 5),
                ("low", 0), ("medium", 2), ("high", 0),
                ("low", 10), ("medium", 0),
            ], start=1)
        ]
        first_result = [i.item_id for i in rank_frontier(items)]
        for _ in range(9):
            result = [i.item_id for i in rank_frontier(items)]
            assert result == first_result

    def test_reversed_input_same_output(self):
        """Reversed input list produces same ranked output."""
        items = [
            self._item(item_id="YOK-1", priority="high", unblocks_count=2),
            self._item(item_id="YOK-2", priority="medium", unblocks_count=5),
            self._item(item_id="YOK-3", priority="low", unblocks_count=0),
        ]
        forward = [i.item_id for i in rank_frontier(items)]
        backward = [i.item_id for i in rank_frontier(list(reversed(items)))]
        assert forward == backward

    def test_shuffled_input_same_output(self):
        """Different orderings of the same items produce same ranked output."""
        import random
        rng = random.Random(42)  # Deterministic seed for reproducibility
        items = [
            self._item(item_id=f"YOK-{i}", priority=p,
                        unblocks_count=u, created_at=f"2026-{m:02d}-01T00:00:00Z")
            for i, (p, u, m) in enumerate([
                ("high", 1, 1), ("medium", 3, 2), ("low", 0, 3),
                ("high", 0, 4), ("medium", 2, 5),
            ], start=1)
        ]
        expected = [i.item_id for i in rank_frontier(items)]
        for _ in range(20):
            shuffled = list(items)
            rng.shuffle(shuffled)
            result = [i.item_id for i in rank_frontier(shuffled)]
            assert result == expected

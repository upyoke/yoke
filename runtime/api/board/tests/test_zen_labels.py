"""Label-extraction tests for yoke_contracts.board.zen.

Companion to ``test_zen.py``. Covers ``_zen_compute_labels`` — stop-word
filtering, frequency cap, label-window narrowing, min-labels widening,
and extra stop-word lists.

Shared fixtures (``zen_db``, ``insert_zen_items``) live in ``conftest.py``.
"""

from __future__ import annotations

from yoke_core.board.db import BoardDB
from yoke_contracts.board.zen import _zen_compute_labels

from runtime.api.board.tests.conftest import insert_zen_items


class TestLabelExtraction:
    def test_basic_extraction(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Board rendering pipeline", "yoke", "done", "2025-01-15"),
            (2, "Deploy automation script", "yoke", "done", "2025-01-20"),
            (3, "Board configuration parser", "yoke", "done", "2025-02-01"),
        ])
        with BoardDB(zen_db) as db:
            labels = _zen_compute_labels(db, "yoke", "2025-01-01")
        assert labels[0] == "board"

    def test_stop_words_filtered(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "Add new feature", "yoke", "done", "2025-01-15"),
            (2, "Fix update issue", "yoke", "done", "2025-01-20"),
        ])
        with BoardDB(zen_db) as db:
            labels = _zen_compute_labels(db, "yoke", "2025-01-01")
        for lab in labels:
            assert lab not in {"add", "new", "fix", "update"}

    def test_max_labels_cap(self, zen_db):
        items = [
            (i, f"word{i} description", "yoke", "done", f"2025-01-{i+1:02d}")
            for i in range(1, 20)
        ]
        insert_zen_items(zen_db, items)
        with BoardDB(zen_db) as db:
            labels = _zen_compute_labels(db, "yoke", "2025-01-01")
        assert len(labels) <= 10

    def test_equal_frequency_ties_sort_reverse_lexicographically(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "alpha feature", "yoke", "done", "2025-01-15"),
            (2, "gamma feature", "yoke", "done", "2025-01-16"),
            (3, "beta feature", "yoke", "done", "2025-01-17"),
        ])
        with BoardDB(zen_db) as db:
            labels = _zen_compute_labels(db, "yoke", "2025-01-01")
        assert labels[:3] == ["gamma", "beta", "alpha"]

    def test_label_days_narrows_window(self, zen_db):
        """label_days>0 ignores the all-time window and filters by recency."""
        import datetime as _dt

        old_day = (_dt.date.today() - _dt.timedelta(days=120)).isoformat()
        recent_day = (_dt.date.today() - _dt.timedelta(days=5)).isoformat()

        insert_zen_items(zen_db, [
            (1, "ancient feature", "yoke", "done", old_day),
            (2, "ancient feature", "yoke", "done", old_day),
            (3, "ancient feature", "yoke", "done", old_day),
            (4, "recent feature", "yoke", "done", recent_day),
        ])
        with BoardDB(zen_db) as db:
            all_time = _zen_compute_labels(db, "yoke", "2000-01-01", 0)
            narrowed = _zen_compute_labels(db, "yoke", "2000-01-01", 30)

        # All-time: ancient dominates (3 > 1)
        assert all_time[0] == "ancient"
        # 30-day window: only recent survives
        assert narrowed == ["recent"]

    def test_df_cap_drops_dominant_word(self, zen_db):
        """df_cap_pct drops any word whose share exceeds the cap."""
        insert_zen_items(zen_db, [
            # "dominant" heads 6/8 titles = 75%
            (1, "dominant thing",  "yoke", "done", "2025-01-10"),
            (2, "dominant stuff",  "yoke", "done", "2025-01-11"),
            (3, "dominant bits",   "yoke", "done", "2025-01-12"),
            (4, "dominant parts",  "yoke", "done", "2025-01-13"),
            (5, "dominant pieces", "yoke", "done", "2025-01-14"),
            (6, "dominant slabs",  "yoke", "done", "2025-01-15"),
            (7, "minor detail",    "yoke", "done", "2025-01-16"),
            (8, "rare quirk",      "yoke", "done", "2025-01-17"),
        ])
        with BoardDB(zen_db) as db:
            no_cap = _zen_compute_labels(db, "yoke", "2000-01-01", 0, 0)
            with_cap = _zen_compute_labels(db, "yoke", "2000-01-01", 0, 50)

        # No cap: dominant wins
        assert no_cap[0] == "dominant"
        # 50% cap: dominant (75%) gets dropped, rare/minor survive
        assert "dominant" not in with_cap
        assert set(with_cap) == {"rare", "minor"}

    def test_min_labels_widens_window(self, zen_db):
        """When the window is too tight, min_labels widens it progressively."""
        import datetime as _dt
        today = _dt.date.today()
        # 2 done items in the last 5 days: not enough
        recent = [
            (1, "alpha recent", "buzz", "done",
             (today - _dt.timedelta(days=1)).isoformat()),
            (2, "beta recent",  "buzz", "done",
             (today - _dt.timedelta(days=2)).isoformat()),
        ]
        # 8 older items, each with a distinct head word
        older = [
            (i + 3, f"{word} old", "buzz", "done",
             (today - _dt.timedelta(days=40)).isoformat())
            for i, word in enumerate(
                ["gamma", "delta", "epsilon", "zeta",
                 "eta", "theta", "iota", "kappa"]
            )
        ]
        insert_zen_items(zen_db, recent + older)

        with BoardDB(zen_db) as db:
            # 5-day window alone: only 2 labels
            tight = _zen_compute_labels(db, "buzz", "2000-01-01", 5, 0)
            # With min=5: widens 5d → 15d → 50d until we hit the floor
            widened = _zen_compute_labels(
                db, "buzz", "2000-01-01", 5, 0, frozenset(), 5
            )

        assert len(tight) == 2
        assert len(widened) >= 5

    def test_extra_stopwords_augment_hardcoded(self, zen_db):
        insert_zen_items(zen_db, [
            (1, "foo real",  "yoke", "done", "2025-01-10"),
            (2, "foo real",  "yoke", "done", "2025-01-11"),
            (3, "foo rare",  "yoke", "done", "2025-01-12"),
        ])
        extras = frozenset({"foo"})
        with BoardDB(zen_db) as db:
            without = _zen_compute_labels(db, "yoke", "2000-01-01", 0, 0)
            withlist = _zen_compute_labels(
                db, "yoke", "2000-01-01", 0, 0, extras
            )
        # Without the extra stopword, "foo" dominates (3 counts vs 2+1).
        assert without[0] == "foo"
        # With "foo" added to stopwords, it drops out and "real" (2) wins.
        assert "foo" not in withlist
        assert withlist[0] == "real"

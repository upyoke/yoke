"""Strategize-carry overflow, deferred-session, and summary tests.

Split from ``test_strategize_carry.py``.

Covers:

* AC-1 / AC-6 overflow: 50 landed items remain fully tracked even when the
  operator-facing summary is display-truncated.
* AC-3 / AC-6 deferred-session: items registered in one session remain
  pending after a second session that defers all changes.
* AC-7: horizon scanning only discovers *new* landings inside the window;
  older pending items still survive because the carry table is the source
  of truth once an item has been seen.
* AC-5: horizon and carry-limit are returned in the candidate set so the
  operator summary can surface them.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from yoke_core.domain.strategize_carry import (
    format_summary,
    get_candidate_set,
    register_new_landings,
)
from runtime.api.test_strategize_carry_test_helpers import (
    _iso,
    _make_db,
    _seed_landed_items,
)


class TestOverflowCase(unittest.TestCase):
    """AC-1 / AC-6: 50 landed items with a display cap of 10.

    Verifies the backing candidate set is complete even though
    ``format_summary`` truncates the printed bucket to 10.
    """

    def test_fifty_items_all_tracked(self):
        conn = _make_db()
        _seed_landed_items(conn, count=50)
        new_ids = register_new_landings(conn, project="yoke")
        self.assertEqual(len(new_ids), 50)

        result = get_candidate_set(
            conn, project="yoke", carry_limit=200, new_ids=new_ids
        )
        self.assertEqual(len(result["new"]), 50)
        self.assertEqual(result["total_pending"], 50)
        self.assertFalse(result["truncated"])

        summary = format_summary(result, display_limit=10)
        # Summary reports the full count and the safety rail truncation note.
        self.assertIn("Pending:** 50 total", summary)
        self.assertIn("(50 new this session", summary)
        self.assertIn("+40 more", summary)
        self.assertIn("Display truncated", summary)


class TestDeferredSessionCase(unittest.TestCase):
    """AC-3 / AC-6: items registered in session 1 remain pending after session 2 defers all."""

    def test_carry_survives_deferred_session(self):
        conn = _make_db()
        _seed_landed_items(conn, count=12)

        # Session 1: register and leave everything pending.
        session1_new = register_new_landings(conn, project="yoke")
        self.assertEqual(len(session1_new), 12)
        session1_result = get_candidate_set(
            conn, project="yoke", new_ids=session1_new
        )
        self.assertEqual(len(session1_result["new"]), 12)

        # Session 2: deferred — no mark calls, no additional landed items.
        # Re-run register-new (should insert nothing new) and rebuild the set.
        session2_new = register_new_landings(conn, project="yoke")
        self.assertEqual(session2_new, [])

        session2_result = get_candidate_set(
            conn, project="yoke", new_ids=session2_new
        )
        self.assertEqual(len(session2_result["new"]), 0)
        self.assertEqual(len(session2_result["carry_forward"]), 12)
        # Deferred sessions must not flip anything to reflected/dismissed.
        self.assertEqual(len(session2_result["reflected"]), 0)
        self.assertEqual(len(session2_result["dismissed"]), 0)

    def test_aged_pending_item_still_surfaces(self):
        """AC-7: horizon bounds discovery only; carry rows never age out."""
        conn = _make_db()
        # One item discovered 5 days ago, then 90 days later the horizon has
        # moved past it, but the row is still in the carry table.
        _seed_landed_items(conn, count=1, days_ago=5)
        register_new_landings(conn, project="yoke", horizon_days=60)

        # Simulate horizon drift: bump merged_at so it is outside the 60d
        # window the next call looks at.
        long_ago = datetime.now(timezone.utc) - timedelta(days=200)
        conn.execute(
            "UPDATE items SET merged_at=%s WHERE id=1",
            (_iso(long_ago),),
        )
        conn.commit()

        second_new = register_new_landings(
            conn, project="yoke", horizon_days=60
        )
        self.assertEqual(second_new, [])  # Outside horizon now.

        result = get_candidate_set(
            conn, project="yoke", horizon_days=60, new_ids=[]
        )
        # The aged item still shows up as carry-forward — the bounded
        # horizon never silently drops pending work.
        self.assertEqual(len(result["carry_forward"]), 1)
        self.assertEqual(result["carry_forward"][0]["item_id"], 1)


class TestFormatSummary(unittest.TestCase):
    """AC-5: horizon + carry limit must appear in the operator summary."""

    def test_horizon_and_limit_in_header(self):
        conn = _make_db()
        _seed_landed_items(conn, count=2)
        new_ids = register_new_landings(conn, project="yoke")
        result = get_candidate_set(
            conn,
            project="yoke",
            horizon_days=45,
            carry_limit=75,
            new_ids=new_ids,
        )
        summary = format_summary(result)
        self.assertIn("last 45d", summary)
        self.assertIn("carry cap: 75", summary)

    def test_truncated_note_when_cap_hit(self):
        conn = _make_db()
        _seed_landed_items(conn, count=5)
        register_new_landings(conn, project="yoke")
        result = get_candidate_set(
            conn, project="yoke", carry_limit=2, new_ids=[]
        )
        summary = format_summary(result)
        self.assertIn("carry-limit cap (2) hit", summary)


if __name__ == "__main__":
    unittest.main()

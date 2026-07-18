"""Tests for the Strategize landed-work carry-forward helper.

These tests exercise the in-memory semantics of
:mod:`yoke_core.domain.strategize_carry` without touching the real DB.
Covers schema bootstrap, register-new-landings delta discovery,
classified candidate set buckets, and mark-state transitions.

Overflow, deferred-session, and operator-summary cases (AC-1, AC-3,
AC-5, AC-6, AC-7) live in ``test_strategize_carry_summary.py``. Shared
helpers live in ``test_strategize_carry_test_helpers``.
"""
from __future__ import annotations

import unittest

from yoke_core.domain import db_backend
from yoke_core.domain.strategize_carry import (
    DEFAULT_CARRY_LIMIT,
    DEFAULT_HORIZON_DAYS,
    ensure_schema,
    get_candidate_set,
    mark_items,
    register_new_landings,
)
from yoke_core.domain.schema_common import _table_exists
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_strategize_carry_test_helpers import (
    PROJECTS_DDL,
    _make_db,
    _seed_landed_items,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestEnsureSchema(unittest.TestCase):
    """Schema bootstrap is idempotent and independent of schema.py."""

    def test_create_is_idempotent(self):
        from runtime.api.fixtures.pg_testdb import (
            connect_test_database,
            create_test_database,
            drop_test_database,
        )

        db_name = create_test_database()
        conn = connect_test_database(db_name)
        try:
            apply_fixture_ddl(conn, PROJECTS_DDL)
            ensure_schema(conn)
            ensure_schema(conn)  # Second call must not raise.
            self.assertTrue(_table_exists(conn, "strategize_landed_carry"))
        finally:
            conn.close()
            drop_test_database(db_name)


class TestRegisterNewLandings(unittest.TestCase):
    """Delta discovery and idempotent insert."""

    def test_new_items_are_inserted_as_pending(self):
        conn = _make_db()
        _seed_landed_items(conn, count=3)
        new_ids = register_new_landings(conn, project="yoke")
        self.assertEqual(sorted(new_ids), [1, 2, 3])

        rows = conn.execute(
            "SELECT item_id, state FROM strategize_landed_carry "
            "WHERE project_id=1 ORDER BY item_id"
        ).fetchall()
        self.assertEqual([dict(r) for r in rows], [
            {"item_id": 1, "state": "pending"},
            {"item_id": 2, "state": "pending"},
            {"item_id": 3, "state": "pending"},
        ])

    def test_second_call_returns_only_net_new(self):
        conn = _make_db()
        _seed_landed_items(conn, count=2)
        first = register_new_landings(conn, project="yoke")
        self.assertEqual(sorted(first), [1, 2])

        # Add one more item and re-run.
        _seed_landed_items(conn, count=1, start_id=3)
        second = register_new_landings(conn, project="yoke")
        self.assertEqual(second, [3])

    def test_outside_horizon_is_ignored(self):
        conn = _make_db()
        _seed_landed_items(conn, count=2, days_ago=120)
        new_ids = register_new_landings(
            conn, project="yoke", horizon_days=60
        )
        self.assertEqual(new_ids, [])
        row = conn.execute(
            "SELECT COUNT(*) FROM strategize_landed_carry"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_project_scoping(self):
        conn = _make_db()
        _seed_landed_items(conn, count=2, project="yoke", start_id=1)
        _seed_landed_items(conn, count=2, project="externalwebapp", start_id=10)

        yoke_new = register_new_landings(conn, project="yoke")
        self.assertEqual(sorted(yoke_new), [1, 2])

        carry_count = conn.execute(
            "SELECT COUNT(*) FROM strategize_landed_carry "
            "WHERE project_id=2"
        ).fetchone()[0]
        self.assertEqual(carry_count, 0)

    def test_null_merged_at_ignored(self):
        conn = _make_db()
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, priority, project_id, project_sequence, merged_at) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
            (1, "No merged_at", "high", 1, 1, None),
        )
        conn.commit()
        new_ids = register_new_landings(conn, project="yoke")
        self.assertEqual(new_ids, [])


class TestGetCandidateSet(unittest.TestCase):
    """Classified candidate set with new vs carry-forward vs reflected vs dismissed."""

    def test_empty_returns_all_buckets(self):
        conn = _make_db()
        result = get_candidate_set(conn, project="yoke")
        self.assertEqual(result["new"], [])
        self.assertEqual(result["carry_forward"], [])
        self.assertEqual(result["reflected"], [])
        self.assertEqual(result["dismissed"], [])
        self.assertEqual(result["total_pending"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["horizon_days"], DEFAULT_HORIZON_DAYS)
        self.assertEqual(result["carry_limit"], DEFAULT_CARRY_LIMIT)

    def test_new_vs_carry_forward_split(self):
        conn = _make_db()
        _seed_landed_items(conn, count=3)
        first_new = register_new_landings(conn, project="yoke")

        # After the first registration, build the candidate set as if this
        # were the same session — all 3 are "new".
        first_result = get_candidate_set(
            conn, project="yoke", new_ids=first_new
        )
        self.assertEqual(len(first_result["new"]), 3)
        self.assertEqual(len(first_result["carry_forward"]), 0)

        # Simulate a second Strategize session with no new landings. Passing
        # an empty new_ids marks all pending rows as carry-forward.
        second_result = get_candidate_set(conn, project="yoke", new_ids=[])
        self.assertEqual(len(second_result["new"]), 0)
        self.assertEqual(len(second_result["carry_forward"]), 3)

    def test_reflected_and_dismissed_buckets(self):
        conn = _make_db()
        _seed_landed_items(conn, count=4)
        register_new_landings(conn, project="yoke")

        mark_items(
            conn,
            project="yoke",
            item_ids=[1],
            state="reflected",
            session_id="s1",
            reason="landed in MASTER-PLAN.md",
        )
        mark_items(
            conn,
            project="yoke",
            item_ids=[2],
            state="dismissed",
            session_id="s1",
            reason="out of scope",
        )

        result = get_candidate_set(conn, project="yoke", new_ids=[])
        self.assertEqual(len(result["carry_forward"]), 2)  # items 3, 4 pending
        self.assertEqual(len(result["reflected"]), 1)
        self.assertEqual(result["reflected"][0]["item_id"], 1)
        self.assertEqual(
            result["reflected"][0]["reason"], "landed in MASTER-PLAN.md"
        )
        self.assertEqual(len(result["dismissed"]), 1)
        self.assertEqual(result["dismissed"][0]["item_id"], 2)

    def test_carry_limit_truncation_flagged(self):
        conn = _make_db()
        _seed_landed_items(conn, count=15)
        register_new_landings(conn, project="yoke")

        result = get_candidate_set(
            conn, project="yoke", carry_limit=5, new_ids=[]
        )
        self.assertEqual(len(result["carry_forward"]), 5)
        self.assertTrue(result["truncated"])

    def test_item_metadata_joined(self):
        conn = _make_db()
        _seed_landed_items(conn, count=1, priority="high")
        register_new_landings(conn, project="yoke")
        result = get_candidate_set(conn, project="yoke", new_ids=[1])
        self.assertEqual(result["new"][0]["priority"], "high")
        self.assertEqual(result["new"][0]["title"], "Landed 1")
        self.assertEqual(result["new"][0]["yok_id"], "YOK-1")


class TestMarkItems(unittest.TestCase):
    """State transitions."""

    def test_mark_pending_to_reflected(self):
        conn = _make_db()
        _seed_landed_items(conn, count=2)
        register_new_landings(conn, project="yoke")
        changed = mark_items(
            conn,
            project="yoke",
            item_ids=[1],
            state="reflected",
            session_id="s1",
        )
        self.assertEqual(changed, 1)
        row = conn.execute(
            "SELECT state FROM strategize_landed_carry "
            "WHERE project_id=1 AND item_id=1"
        ).fetchone()
        self.assertEqual(row[0], "reflected")

    def test_mark_invalid_state_raises(self):
        conn = _make_db()
        with self.assertRaises(ValueError):
            mark_items(
                conn,
                project="yoke",
                item_ids=[1],
                state="bogus",
            )

    def test_mark_unknown_item_upserts(self):
        """Operator pre-seeding a dismissal should create the row."""
        conn = _make_db()
        changed = mark_items(
            conn,
            project="yoke",
            item_ids=[999],
            state="dismissed",
            session_id="s1",
            reason="never relevant",
        )
        self.assertEqual(changed, 1)
        row = conn.execute(
            "SELECT state, reason FROM strategize_landed_carry "
            "WHERE project_id=1 AND item_id=999"
        ).fetchone()
        self.assertEqual(row["state"], "dismissed")
        self.assertEqual(row["reason"], "never relevant")


if __name__ == "__main__":
    unittest.main()

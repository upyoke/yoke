"""Tests for yoke_core.domain.check_hard_blocks."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import pytest

from yoke_core.domain import check_hard_blocks as mod
from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'issue',
    status TEXT NOT NULL DEFAULT 'idea',
    priority TEXT NOT NULL DEFAULT 'medium',
    worktree TEXT,
    project_id INTEGER NOT NULL DEFAULT 1,
    project_sequence INTEGER NOT NULL,
    merged_at TEXT
);
CREATE TABLE item_dependencies (
    id INTEGER PRIMARY KEY,
    dependent_item TEXT NOT NULL,
    blocking_item TEXT NOT NULL,
    gate_point TEXT NOT NULL,
    satisfaction TEXT NOT NULL
);
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT ''
);
INSERT INTO projects (id, slug, name)
VALUES (1, 'yoke', 'Yoke')
ON CONFLICT(id) DO NOTHING;
"""


def _apply_schema() -> None:
    """Build the local 3-table schema against the backend-resolved test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`: resolves its
    connection through the backend factory and executes the schema one native
    statement at a time.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestNormalizeId(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(mod._normalize_item_id(TEST_ITEM_REF), TEST_ITEM_ID)
        self.assertEqual(mod._normalize_item_id(str(TEST_ITEM_ID)), TEST_ITEM_ID)
        self.assertEqual(mod._normalize_item_id("007"), 7)

    def test_invalid(self) -> None:
        self.assertIsNone(mod._normalize_item_id("abc"))
        self.assertIsNone(mod._normalize_item_id(""))


class TestSatisfiedSetsFromLifecycle(unittest.TestCase):
    """Ensure the status sets are derived from the lifecycle module."""

    def test_at_or_past_implemented_contains_expected(self) -> None:
        for status in ("implemented", "release", "done"):
            self.assertIn(status, mod._AT_OR_PAST_IMPLEMENTED)
        for status in ("idea", "implementing", "reviewing-implementation"):
            self.assertNotIn(status, mod._AT_OR_PAST_IMPLEMENTED)

    def test_merged_statuses_contains_expected(self) -> None:
        for status in ("release", "done"):
            self.assertIn(status, mod._MERGED_STATUSES)
        for status in ("implemented", "reviewed-implementation"):
            self.assertNotIn(status, mod._MERGED_STATUSES)


class TestIsSatisfied(unittest.TestCase):
    def test_status_done(self) -> None:
        self.assertTrue(mod._is_satisfied("status:done", {"status": "done"}, None))
        self.assertFalse(
            mod._is_satisfied("status:done", {"status": "implemented"}, None)
        )

    def test_status_implemented(self) -> None:
        for status in ("implemented", "release", "done"):
            self.assertTrue(
                mod._is_satisfied("status:implemented", {"status": status}, None)
            )
        self.assertFalse(
            mod._is_satisfied(
                "status:implemented", {"status": "implementing"}, None
            )
        )

    def test_fact_merged_via_merged_at(self) -> None:
        item = {"status": "implemented", "merged_at": "2026-01-01T00:00:00Z"}
        self.assertTrue(mod._is_satisfied("fact:merged", item, None))

    def test_fact_merged_via_release_status(self) -> None:
        item = {"status": "release", "merged_at": None, "worktree": None}
        self.assertTrue(mod._is_satisfied("fact:merged", item, None))

    def test_fact_merged_unmet(self) -> None:
        item = {"status": "implementing", "merged_at": None, "worktree": None}
        self.assertFalse(mod._is_satisfied("fact:merged", item, None))

    def test_unknown_satisfaction_fails_safe(self) -> None:
        self.assertFalse(mod._is_satisfied("some-other", {"status": "done"}, None))


class TestEvaluateBlockers(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        # The seam owns the per-test DB lifecycle: a real file under tmp_path on
        # SQLite, a disposable per-test database (dropped on context exit) on
        # Postgres. YOKE_DB is bound for the test body so the code-under-test
        # (evaluate_blockers -> db_helpers.connect -> YOKE_DB on SQLite) and
        # the insert helpers (connect_test_db(db_path)) hit the same database;
        # on Postgres the binding is inert and the repointed YOKE_PG_DSN that
        # init_test_db keeps active for the context selects the per-test DB.
        with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
            self.db_path = db_path
            with mock.patch.dict(
                os.environ, {"YOKE_DB": db_path}, clear=False
            ):
                yield

    def _insert_item(
        self,
        item_id: int,
        title: str,
        status: str = "idea",
        worktree: str = None,
        project_id: int = 1,
        merged_at: str = None,
    ) -> None:
        conn = connect_test_db(self.db_path)
        p = _p(conn)
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, worktree, "
            "project_id, project_sequence, merged_at) "
            f"VALUES ({p}, {p}, 'issue', {p}, 'medium', {p}, {p}, {p}, {p})",
            (item_id, title, status, worktree, project_id, item_id, merged_at),
        )
        conn.commit()
        conn.close()

    def _insert_dep(
        self,
        dependent: int,
        blocking: int,
        gate_point: str,
        satisfaction: str,
    ) -> None:
        conn = connect_test_db(self.db_path)
        p = _p(conn)
        conn.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item, blocking_item, gate_point, satisfaction) "
            f"VALUES ({p}, {p}, {p}, {p})",
            (f"YOK-{dependent}", f"YOK-{blocking}", gate_point, satisfaction),
        )
        conn.commit()
        conn.close()

    def test_empty_blockers(self) -> None:
        self._insert_item(42, "Orphan")
        self.assertEqual(mod.evaluate_blockers(42), [])

    def test_satisfied_status_done_filtered(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_item(10, "Blocker", status="done")
        self._insert_dep(42, 10, "activation", "status:done")
        self.assertEqual(mod.evaluate_blockers(42), [])

    def test_unsatisfied_status_done_reported(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_item(10, "Blocker", status="implementing")
        self._insert_dep(42, 10, "activation", "status:done")
        lines = mod.evaluate_blockers(42)
        self.assertEqual(len(lines), 1)
        self.assertIn("YOK-10", lines[0])
        self.assertIn("implementing", lines[0])
        self.assertIn("Blocker", lines[0])
        self.assertIn("activation", lines[0])
        self.assertIn("status:done", lines[0])

    def test_missing_blocker_item_reported(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_dep(42, 99, "integration", "fact:merged")
        lines = mod.evaluate_blockers(42)
        self.assertEqual(len(lines), 1)
        self.assertIn("YOK-99", lines[0])
        self.assertIn("missing", lines[0])

    def test_status_implemented_satisfied(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_item(10, "Blocker", status="implemented")
        self._insert_dep(42, 10, "activation", "status:implemented")
        self.assertEqual(mod.evaluate_blockers(42), [])

    def test_fact_merged_via_release(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_item(10, "Blocker", status="release")
        self._insert_dep(42, 10, "integration", "fact:merged")
        self.assertEqual(mod.evaluate_blockers(42), [])

    def test_gate_filter_respected(self) -> None:
        self._insert_item(42, "Dependent")
        self._insert_item(10, "Blocker", status="idea")
        self._insert_dep(42, 10, "activation", "status:done")
        self._insert_dep(42, 10, "integration", "fact:merged")
        # Filter to integration: only the fact:merged row should be evaluated
        lines_int = mod.evaluate_blockers(42, gate_filter="integration")
        self.assertEqual(len(lines_int), 1)
        self.assertIn("integration", lines_int[0])
        self.assertIn("fact:merged", lines_int[0])
        # Filter to activation: only the status:done row
        lines_act = mod.evaluate_blockers(42, gate_filter="activation")
        self.assertEqual(len(lines_act), 1)
        self.assertIn("activation", lines_act[0])


class TestMain(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = mod.main(argv)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_usage_error_when_id_invalid(self) -> None:
        rc, _, err = self._run(["not-an-id"])
        self.assertEqual(rc, 2)
        self.assertIn("could not parse", err)

    def test_exit_0_when_clear(self) -> None:
        with mock.patch.object(mod, "evaluate_blockers", return_value=[]):
            rc, out, _ = self._run([TEST_ITEM_REF])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_exit_1_when_blocked(self) -> None:
        with mock.patch.object(
            mod,
            "evaluate_blockers",
            return_value=["BLOCKED|YOK-10|idea|Something|activation|status:done"],
        ):
            rc, out, _ = self._run([TEST_ITEM_REF])
        self.assertEqual(rc, 1)
        self.assertIn("BLOCKED|YOK-10", out)

    def test_gate_point_forwarded(self) -> None:
        calls: list[tuple[int, str]] = []

        def fake(item_id, gate_filter=None):
            calls.append((item_id, gate_filter))
            return []

        with mock.patch.object(mod, "evaluate_blockers", side_effect=fake):
            self._run([TEST_ITEM_REF, "--gate-point", "integration"])
        self.assertEqual(calls, [(TEST_ITEM_ID, "integration")])


if __name__ == "__main__":
    unittest.main()

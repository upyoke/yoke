"""Tests for the Yoke function-call dispatcher event-registry seed."""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.event_registry_seed_yoke_function_call import (
    SEED_ROWS,
    seed,
    seeded_event_names,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_empty_registry_schema() -> None:
    """``init_test_db`` strategy: an empty ``event_registry`` table.

    Resolves its connection through the backend factory so the same table
    builds on both engines and the factory-routed ``seed`` write and the
    ``connect_test_db`` read-back land on the same per-test DB.
    """
    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE event_registry (
                event_name TEXT PRIMARY KEY,
                event_kind TEXT NOT NULL,
                event_type TEXT NOT NULL,
                owner_service TEXT NOT NULL,
                description TEXT NOT NULL,
                context_schema TEXT,
                severity_default TEXT NOT NULL DEFAULT 'INFO',
                added_in TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


class TestSeedRows(unittest.TestCase):
    """Static contract: the expected event names and metadata."""

    def test_includes_all_event_names(self):
        names = set(row[0] for row in SEED_ROWS)
        self.assertEqual(
            names,
            {
                "YokeFunctionCalled",
                "DispatcherIdempotencyReplay",
                "DispatcherDownstreamDegraded",
                "YokeFunctionPermissionDenied",
            },
        )

    def test_all_event_kind_is_lifecycle(self):
        kinds = {row[1] for row in SEED_ROWS}
        self.assertEqual(kinds, {"lifecycle"})

    def test_all_event_type_is_function_call(self):
        types = {row[2] for row in SEED_ROWS}
        self.assertEqual(types, {"function_call"})

    def test_owner_service_is_cli(self):
        services = {row[3] for row in SEED_ROWS}
        self.assertEqual(services, {"cli"})

    def test_descriptions_non_empty_and_single_line(self):
        for row in SEED_ROWS:
            self.assertTrue(row[4])
            self.assertNotIn("\n", row[4])

    def test_degraded_severity_is_canonical_warn(self):
        rows = {row[0]: row for row in SEED_ROWS}
        self.assertEqual(rows["DispatcherDownstreamDegraded"][5], "WARN")
        self.assertEqual(rows["YokeFunctionPermissionDenied"][5], "WARN")
        self.assertEqual(rows["YokeFunctionCalled"][5], "INFO")
        self.assertEqual(rows["DispatcherIdempotencyReplay"][5], "INFO")

    def test_seeded_event_names_helper_matches(self):
        helper = set(seeded_event_names())
        rows = set(row[0] for row in SEED_ROWS)
        self.assertEqual(helper, rows)


class TestSeedApply(unittest.TestCase):
    def setUp(self) -> None:
        # Per-test DB on both backends (file on SQLite, disposable per-test
        # Postgres database with the DSN repointed on Postgres). The seed's
        # factory-routed write and the read-back both target this same DB.
        self._stack = contextlib.ExitStack()
        self._tmp_dir = tempfile.mkdtemp(prefix="yoke-test-seed-")
        self.db_path = self._stack.enter_context(
            init_test_db(
                Path(self._tmp_dir), apply_schema=_apply_empty_registry_schema
            )
        )

    def tearDown(self) -> None:
        self._stack.close()
        for child in Path(self._tmp_dir).glob("*"):
            child.unlink(missing_ok=True)
        Path(self._tmp_dir).rmdir()

    def _rows(self) -> list[tuple]:
        conn = connect_test_db(self.db_path)
        try:
            return conn.execute(
                "SELECT event_name, event_kind, event_type, owner_service, "
                "description, severity_default, status FROM event_registry "
                "ORDER BY event_name"
            ).fetchall()
        finally:
            conn.close()

    def test_seed_inserts_active_rows(self):
        seed(db_path=self.db_path)
        rows = self._rows()
        self.assertEqual(len(rows), 4)
        names = sorted(r[0] for r in rows)
        self.assertEqual(
            names,
            sorted(
                [
                    "DispatcherDownstreamDegraded",
                    "DispatcherIdempotencyReplay",
                    "YokeFunctionPermissionDenied",
                    "YokeFunctionCalled",
                ]
            ),
        )
        for row in rows:
            self.assertEqual(row[6], "active")
            self.assertEqual(row[1], "lifecycle")
            self.assertEqual(row[2], "function_call")
            self.assertEqual(row[3], "cli")

    def test_seed_is_idempotent(self):
        seed(db_path=self.db_path)
        first = self._rows()
        seed(db_path=self.db_path)
        second = self._rows()
        # Compare by value: the Postgres facade's row objects do not value-equal
        # across instances, so normalize each row to a tuple first.
        self.assertEqual(
            [tuple(r) for r in first],
            [tuple(r) for r in second],
        )

    def test_seed_does_not_overwrite_existing_row(self):
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, "
            "event_type, owner_service, description, severity_default, "
            f"status) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                "YokeFunctionCalled",
                "lifecycle",
                "function_call",
                "cli",
                "PRESERVED - operator amended",
                "INFO",
                "active",
            ),
        )
        conn.commit()
        conn.close()
        seed(db_path=self.db_path)
        rows = {r[0]: r for r in self._rows()}
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            rows["YokeFunctionCalled"][4],
            "PRESERVED - operator amended",
        )


if __name__ == "__main__":
    unittest.main()

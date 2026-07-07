"""Tests for the event-registry seed (path-claim + session-cwd guards).

Verifies all 5 rows land with the expected metadata and that the seed
is idempotent (re-running does not duplicate rows or mutate existing
ones).
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.event_registry_seed_path_claim_session_cwd import (
    SEED_ROWS,
    seed,
    seeded_event_names,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_empty_registry_schema() -> None:
    """``init_test_db`` strategy: an empty ``event_registry`` table.

    Resolves its connection through the backend factory (``YOKE_DB`` on
    SQLite, the repointed ``YOKE_PG_DSN`` on Postgres) so the same table
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
    """Static contract: the 5 expected event names, types, and metadata."""

    def test_TC_seed_includes_all_event_names(self):
        names = set(row[0] for row in SEED_ROWS)
        self.assertEqual(
            names,
            {
                "PathClaimEditGuardDenied",
                "PathClaimBashGuardDenied",
                "SessionCwdMismatchDenied",
                "SessionCwdMismatchAllowedReadOnly",
                "SessionCwdBindingFailOpen",
                "SessionCwdBindingHealthCheckFailed",
            },
        )

    def test_TC_path_claim_events_share_event_type(self):
        types_for_pc = {
            row[2] for row in SEED_ROWS if row[0].startswith("PathClaim")
        }
        self.assertEqual(types_for_pc, {"path_claim"})

    def test_TC_session_cwd_events_share_event_type(self):
        types_for_sc = {
            row[2] for row in SEED_ROWS if row[0].startswith("SessionCwd")
        }
        self.assertEqual(types_for_sc, {"session_cwd"})

    def test_TC_all_owner_service_is_cli(self):
        services = {row[3] for row in SEED_ROWS}
        self.assertEqual(services, {"cli"})

    def test_TC_all_event_kind_is_lifecycle(self):
        kinds = {row[1] for row in SEED_ROWS}
        self.assertEqual(kinds, {"lifecycle"})

    def test_TC_all_descriptions_non_empty(self):
        for row in SEED_ROWS:
            self.assertTrue(row[4])
            # One-line description (no newlines).
            self.assertNotIn("\n", row[4])

    def test_TC_seeded_event_names_helper_matches(self):
        helper_names = set(seeded_event_names())
        row_names = set(row[0] for row in SEED_ROWS)
        self.assertEqual(helper_names, row_names)


class TestSeedApply(unittest.TestCase):
    """Behavioral contract: the seed actually inserts the rows."""

    def setUp(self) -> None:
        # Per-test DB on both backends: a real SQLite file under a temp dir on
        # SQLite; a disposable per-test Postgres database (DSN repointed for the
        # test's lifetime) on Postgres. The seed's factory-routed write and the
        # read-back both resolve to this same per-test DB.
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

    def _registry_rows(self) -> list[tuple]:
        conn = connect_test_db(self.db_path)
        try:
            return conn.execute(
                "SELECT event_name, event_kind, event_type, owner_service, "
                "description, severity_default, status "
                "FROM event_registry ORDER BY event_name"
            ).fetchall()
        finally:
            conn.close()

    def test_TC_seed_inserts_all_rows(self):
        seed(db_path=self.db_path)
        rows = self._registry_rows()
        expected = sorted(
            [
                "PathClaimBashGuardDenied",
                "PathClaimEditGuardDenied",
                "SessionCwdBindingFailOpen",
                "SessionCwdBindingHealthCheckFailed",
                "SessionCwdMismatchAllowedReadOnly",
                "SessionCwdMismatchDenied",
            ]
        )
        self.assertEqual(len(rows), len(expected))
        names = sorted(row[0] for row in rows)
        self.assertEqual(names, expected)

    def test_TC_seeded_rows_active_with_correct_metadata(self):
        seed(db_path=self.db_path)
        rows = {row[0]: row for row in self._registry_rows()}
        for name in (
            "PathClaimEditGuardDenied",
            "PathClaimBashGuardDenied",
        ):
            row = rows[name]
            self.assertEqual(row[1], "lifecycle")  # event_kind
            self.assertEqual(row[2], "path_claim")  # event_type
            self.assertEqual(row[3], "cli")  # owner_service
            self.assertEqual(row[6], "active")  # status
            self.assertTrue(row[4])  # description non-empty
        for name in (
            "SessionCwdMismatchDenied",
            "SessionCwdMismatchAllowedReadOnly",
            "SessionCwdBindingFailOpen",
            "SessionCwdBindingHealthCheckFailed",
        ):
            row = rows[name]
            self.assertEqual(row[1], "lifecycle")
            self.assertEqual(row[2], "session_cwd")
            self.assertEqual(row[3], "cli")
            self.assertEqual(row[6], "active")
            self.assertTrue(row[4])
        self.assertEqual(
            rows["SessionCwdMismatchAllowedReadOnly"][5], "INFO"
        )

    def test_TC_seed_is_idempotent(self):
        seed(db_path=self.db_path)
        first_rows = self._registry_rows()
        seed(db_path=self.db_path)
        second_rows = self._registry_rows()
        # Compare by value: the Postgres facade's row objects do not value-equal
        # across instances, so normalize each row to a tuple first.
        self.assertEqual(
            [tuple(r) for r in first_rows],
            [tuple(r) for r in second_rows],
        )

    def test_TC_seed_does_not_overwrite_existing_row(self):
        # Pre-populate one row with a custom description; seed must
        # preserve it (idempotent upsert keyed on event_name). This
        # protects the registry from drift when an operator has manually
        # amended a row.
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, "
            "event_type, owner_service, description, severity_default, "
            f"status) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                "PathClaimEditGuardDenied",
                "lifecycle",
                "path_claim",
                "cli",
                "PRESERVED — operator amended description",
                "WARNING",
                "active",
            ),
        )
        conn.commit()
        conn.close()

        seed(db_path=self.db_path)
        rows = {row[0]: row for row in self._registry_rows()}
        # All seeded rows present.
        self.assertEqual(len(rows), len(SEED_ROWS))
        # The pre-existing row's description was NOT overwritten.
        self.assertEqual(
            rows["PathClaimEditGuardDenied"][4],
            "PRESERVED — operator amended description",
        )


if __name__ == "__main__":
    unittest.main()

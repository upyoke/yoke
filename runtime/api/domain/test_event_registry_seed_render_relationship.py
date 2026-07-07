"""Tests for the render-relationship event-registry seed."""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.event_registry_seed_render_relationship import (
    EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
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
    def test_event_name_constant_matches_seed(self):
        names = {row[0] for row in SEED_ROWS}
        self.assertIn(EVENT_NAME_RENDER_RELATIONSHIP_RECORDED, names)

    def test_event_kind_is_lifecycle(self):
        kinds = {row[1] for row in SEED_ROWS}
        self.assertEqual(kinds, {"lifecycle"})

    def test_event_type_is_path_context(self):
        types = {row[2] for row in SEED_ROWS}
        self.assertEqual(types, {"path_context"})

    def test_owner_service_is_cli(self):
        services = {row[3] for row in SEED_ROWS}
        self.assertEqual(services, {"cli"})

    def test_descriptions_single_line_non_empty(self):
        for row in SEED_ROWS:
            self.assertTrue(row[4])
            self.assertNotIn("\n", row[4])

    def test_seeded_event_names_matches_seed_rows(self):
        self.assertEqual(
            set(seeded_event_names()),
            {row[0] for row in SEED_ROWS},
        )


class TestSeedApply(unittest.TestCase):
    def setUp(self) -> None:
        # Per-test DB on both backends (file on SQLite, disposable per-test
        # Postgres database with the DSN repointed on Postgres). The seed's
        # factory-routed write and the read-back both target this same DB.
        self._stack = contextlib.ExitStack()
        self._tmp_dir = tempfile.mkdtemp(prefix="yoke-test-seed-render-")
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

    def test_seed_inserts_active_row(self):
        seed(db_path=self.db_path)
        rows = self._rows()
        self.assertEqual(len(rows), len(SEED_ROWS))
        for row in rows:
            self.assertEqual(row[6], "active")
            self.assertEqual(row[1], "lifecycle")
            self.assertEqual(row[2], "path_context")
            self.assertEqual(row[3], "cli")

    def test_seed_is_idempotent(self):
        seed(db_path=self.db_path)
        first = self._rows()
        seed(db_path=self.db_path)
        # Compare by value: the Postgres facade's row objects do not value-equal
        # across instances, so normalize each row to a tuple first.
        self.assertEqual(
            [tuple(r) for r in first],
            [tuple(r) for r in self._rows()],
        )

    def test_seed_does_not_overwrite_existing_row(self):
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        conn.execute(
            "INSERT INTO event_registry (event_name, event_kind, "
            "event_type, owner_service, description, severity_default, "
            f"status) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})",
            (
                EVENT_NAME_RENDER_RELATIONSHIP_RECORDED,
                "lifecycle",
                "path_context",
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
        self.assertEqual(
            rows[EVENT_NAME_RENDER_RELATIONSHIP_RECORDED][4],
            "PRESERVED - operator amended",
        )


if __name__ == "__main__":
    unittest.main()

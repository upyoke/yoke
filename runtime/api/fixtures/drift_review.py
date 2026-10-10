"""Disposable native-clock database and delivery seeds for drift review."""

from __future__ import annotations

import unittest
from typing import Optional

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.test_dependency_schema import PROJECTS_SCHEMA

TEST_ITEM_ID = 42


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _apply_drift_schema() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the drift-review tests.

    Builds the minimal ``items`` + ``strategy_checkpoints`` +
    ``item_status_transitions`` tables the drift-review queries exercise
    (deliberately NOT the full production schema). Resolves its own
    connection through the backend factory (``YOKE_DB`` on SQLite, the
    repointed per-test ``YOKE_PG_DSN`` on Postgres), so each test gets an
    isolated table set that never collides with the ambient production
    relations on Postgres.
    """
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            PROJECTS_SCHEMA
            + """CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                title TEXT,
                status TEXT DEFAULT 'done',
                priority TEXT DEFAULT 'low',
                project_id INTEGER NOT NULL DEFAULT 1,
                project_sequence INTEGER,
                merged_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ
            );
            CREATE TABLE strategy_checkpoints (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            );
            CREATE TABLE item_status_transitions (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL,
                task_num INTEGER,
                to_status TEXT NOT NULL,
                project_id INTEGER,
                created_at TIMESTAMPTZ NOT NULL
            );""",
        )
    finally:
        conn.close()


def _project_id(slug: str) -> int:
    return 2 if slug == "externalwebapp" else 1


def _insert_drift_item(
    conn,
    item_id: int,
    title: str,
    priority: str,
    project: str = "yoke",
    merged_at: Optional[str] = None,
    project_sequence: Optional[int] = None,
) -> None:
    """Insert one delivered item, identity included. A case asserting a
    rendered reference passes its own ``project_sequence`` so the
    assertion cannot pass by the two counters coinciding."""
    p = _placeholder(conn)
    columns = "id, title, priority, project_id, project_sequence"
    values = f"{p}, {p}, {p}, {p}, {p}"
    sequence = item_id if project_sequence is None else project_sequence
    params = [item_id, title, priority, _project_id(project), sequence]
    if merged_at is not None:
        columns += ", merged_at"
        values += f", {p}"
        params.append(merged_at)
    conn.execute(
        f"INSERT INTO items ({columns}) VALUES ({values})",
        tuple(params),
    )


class _DriftDbCase(unittest.TestCase):
    """Base providing a backend-aware per-test drift-review DB.

    The autouse fixture owns the per-test DB lifecycle (a real file on SQLite,
    a disposable per-test database on Postgres dropped on teardown). Subclass
    tests call :meth:`_make_db` for a backend-aware connection to it.
    """

    @pytest.fixture(autouse=True)
    def _drift_db(self, tmp_path):
        with init_test_db(tmp_path, apply_schema=_apply_drift_schema) as db_path:
            self._db_path = db_path
            yield

    def _make_db(self):
        """Backend-aware connection to this test's drift-review DB."""
        return connect_test_db(self._db_path)

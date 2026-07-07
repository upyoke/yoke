"""Shared backend-aware test scaffolding for the item_field_transform suite.

Owns the local items + item_sections DDL, the init_test_db apply_schema
strategy, the _FakeDB per-test-DB stub, and the _patched_db routing helper —
shared by the four test_item_field_transform* modules so the _SCHEMA literal
and the stub live in exactly one place.
"""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    sections,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.schema_init_apply import execute_schema_script


_SCHEMA = """
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    spec TEXT, design_spec TEXT, technical_plan TEXT,
    worktree_plan TEXT, shepherd_log TEXT,
    shepherd_caveats TEXT, test_results TEXT, deploy_log TEXT,
    browser_qa_metadata TEXT, db_mutation_profile TEXT,
    db_compatibility_attestation TEXT,
    updated_at TEXT, spec_updated_at TEXT, spec_updated_by TEXT
);
CREATE TABLE item_sections (
    item_id INTEGER, section_name TEXT, content TEXT,
    ordering INTEGER, source TEXT DEFAULT 'operator',
    created_at TEXT, updated_at TEXT,
    PRIMARY KEY(item_id, section_name)
);
"""


def _apply_schema() -> None:
    """Build the local items + item_sections schema on the resolved test DB.

    Zero-arg ``apply_schema`` strategy for :func:`init_test_db`: resolves its
    connection through the backend factory with ``YOKE_PG_DSN`` repointed to a
    disposable per-test Postgres database so the tables land in the same
    authority the code-under-test reads. The facade translates the ``INTEGER
    PRIMARY KEY`` columns.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class _FakeDB:
    """Backend-aware stub for the structured-write + sections paths.

    ``execute_structured_write`` closes its connection after every call, so
    we cannot share a single handle. :func:`init_test_db` owns the per-test DB
    lifecycle (a disposable per-test database with ``YOKE_PG_DSN`` repointed
    for the stub's lifetime); every consumer opens its own connection against
    it.
    """

    def __init__(self) -> None:
        self._stack = contextlib.ExitStack()
        tmp_dir = Path(tempfile.mkdtemp(prefix="yoke-test-item-field-transform-"))
        self._tmp_dir = tmp_dir
        self.path = self._stack.enter_context(
            init_test_db(tmp_dir, apply_schema=_apply_schema)
        )

    def insert_item(self, item_id: int, **fields: Optional[str]) -> None:
        cols = ["id"] + list(fields.keys())
        with connect_test_db(self.path) as conn:
            marks = ", ".join([_placeholder(conn)] * len(cols))
            conn.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({marks})",
                (item_id, *fields.values()),
            )

    def fetch_item_field(self, item_id: int, field: str) -> Optional[str]:
        with connect_test_db(self.path) as conn:
            p = _placeholder(conn)
            row = conn.execute(
                f"SELECT {field} FROM items WHERE id = {p}", (item_id,),
            ).fetchone()
        return row[0] if row else None

    def fetch_section(self, item_id: int, name: str) -> Optional[str]:
        with connect_test_db(self.path) as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT content FROM item_sections "
                f"WHERE item_id={p} AND section_name={p}",
                (item_id, name),
            ).fetchone()
        return row[0] if row else None

    def fetch_section_ordering(self, item_id: int, name: str) -> Optional[int]:
        with connect_test_db(self.path) as conn:
            p = _placeholder(conn)
            row = conn.execute(
                "SELECT ordering FROM item_sections "
                f"WHERE item_id={p} AND section_name={p}",
                (item_id, name),
            ).fetchone()
        return row[0] if row else None

    def cleanup(self) -> None:
        self._stack.close()
        import shutil

        shutil.rmtree(self._tmp_dir, ignore_errors=True)


def _patched_db(test: unittest.TestCase, db: _FakeDB) -> None:
    """Route every helper read/write through ``db`` for the test's lifetime.

    Both ``item_field_transform`` and ``backlog_structured_write_op``
    imported ``_resolve_write_db_path`` directly, so each binding needs its
    own patch. Body render + GitHub sync are stubbed for hermeticity.
    """
    test.addCleanup(db.cleanup)
    from yoke_core.domain import db_helpers as _db_helpers
    targets = [
        (backlog_queries, "_resolve_write_db_path", db.path),
        (backlog_queries, "_assert_write_db_ready", None),
        (backlog_structured_write_op, "_resolve_write_db_path", db.path),
        (backlog_structured_write_op, "_assert_write_db_ready", None),
        (item_field_transform, "_resolve_write_db_path", db.path),
        (backlog_rendering, "_render_body", True),
        (backlog_rendering, "_sync_body", (True, "full")),
        (backlog_rendering, "_maybe_rebuild_board", None),
        (sections, "_render_fn", 0),
        (sections, "_emit_event_fn", None),
        (_db_helpers, "resolve_db_path", db.path),
    ]
    for module, name, value in targets:
        patcher = mock.patch.object(module, name, return_value=value)
        patcher.start()
        test.addCleanup(patcher.stop)

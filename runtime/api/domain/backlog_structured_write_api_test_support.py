# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import shutil

import tempfile

import unittest

from pathlib import Path

from typing import Optional

from unittest import mock

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain import (
    backlog_queries,
    backlog_rendering,
    backlog_structured_write_op,
    db_backend,
    item_field_transform,
    sections,
)

from yoke_core.domain.handlers import (
    items_structured_field,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


def _apply_fake_db_schema() -> None:
    """init_test_db apply_schema strategy: items + item_sections subset."""
    conn = db_backend.connect()
    try:
        conn.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, spec TEXT, "
            "design_spec TEXT, technical_plan TEXT, worktree_plan TEXT, "
            "shepherd_caveats TEXT, test_results TEXT, "
            "deploy_log TEXT, db_mutation_profile "
            "TEXT, db_compatibility_attestation TEXT, architecture_impact "
            "TEXT, updated_at TIMESTAMPTZ, spec_updated_at TIMESTAMPTZ, spec_updated_by TEXT)"
        )
        conn.execute(
            "CREATE TABLE item_sections (item_id INTEGER, section_name TEXT, "
            "content TEXT, ordering INTEGER, source TEXT DEFAULT 'operator', "
            "created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, PRIMARY KEY(item_id, section_name))"
        )
        conn.commit()
    finally:
        conn.close()


class _FakeDB:
    """Backend-aware per-test DB stub."""

    def __init__(self) -> None:
        self._tmpdir = tempfile.mkdtemp(
            prefix="yoke-test-backlog-structured-write-api-",
        )
        self._db_ctx = init_test_db(
            Path(self._tmpdir),
            apply_schema=_apply_fake_db_schema,
        )
        self.path = self._db_ctx.__enter__()

    def insert_item(self, item_id: int, **fields: Optional[str]) -> None:
        cols = ["id"] + list(fields.keys())
        with connect_test_db(self.path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            marks = ", ".join([p] * len(cols))
            conn.execute(
                f"INSERT INTO items ({', '.join(cols)}) VALUES ({marks})",
                (item_id, *fields.values()),
            )

    def fetch_field(self, item_id: int, field: str) -> Optional[str]:
        with connect_test_db(self.path) as conn:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                f"SELECT {field} FROM items WHERE id = {p}",
                (item_id,),
            ).fetchone()
        return row[0] if row else None

    def cleanup(self) -> None:
        self._db_ctx.__exit__(None, None, None)
        shutil.rmtree(self._tmpdir, ignore_errors=True)


def _patched_db(test: unittest.TestCase, db: _FakeDB) -> None:
    test.addCleanup(db.cleanup)
    targets = [
        (backlog_queries, "_resolve_write_db_path", db.path),
        (backlog_queries, "_assert_write_db_ready", None),
        (backlog_structured_write_op, "_resolve_write_db_path", db.path),
        (backlog_structured_write_op, "_assert_write_db_ready", None),
        (item_field_transform, "_resolve_write_db_path", db.path),
        (items_structured_field, "_resolve_write_db_path", db.path),
        (backlog_rendering, "_render_body", True),
        (backlog_rendering, "_sync_body", (True, "full")),
        (sections, "_render_fn", 0),
        (sections, "_emit_event_fn", None),
    ]
    for module, name, value in targets:
        patcher = mock.patch.object(module, name, return_value=value)
        patcher.start()
        test.addCleanup(patcher.stop)

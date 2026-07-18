"""Shared fixtures and constants for the emit-event test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import events_crud
from runtime.api.fixtures.file_test_db import init_test_db

# Synthetic test item ID — not a real backlog item reference.
TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _apply_emit_event_schema() -> None:
    """``apply_schema`` strategy: events tables + a minimal items row.

    ``events_crud.cmd_init`` resolves its connection through the backend factory
    (``YOKE_DB`` on SQLite, the repointed ``YOKE_PG_DSN`` on Postgres). The
    items table/seed is created via the factory too.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
            )
            """
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK')"
        )
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (2, 'externalwebapp', 'ExternalWebapp', 'EXT')"
        )
        conn.commit()
    finally:
        conn.close()
    events_crud.cmd_init()
    conn = db_backend.connect()
    try:
        conn.execute(
            """
            CREATE TABLE items (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id),
                project_sequence INTEGER NOT NULL,
                UNIQUE(project_id, project_sequence)
            )
            """
        )
        conn.execute(
            "INSERT INTO items (id, project_id, project_sequence) "
            f"VALUES ({TEST_ITEM_ID}, 2, {TEST_ITEM_ID})"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def events_db(tmp_path: Path, monkeypatch):
    """Backend-aware temp Yoke DB with events tables + a minimal items row.

    SQLite: a real file under ``tmp_path``. Postgres: a disposable per-test
    database with ``YOKE_PG_DSN`` repointed for the context and dropped on
    teardown, so factory-routed emit_event calls land in an isolated DB.
    """
    with init_test_db(tmp_path, apply_schema=_apply_emit_event_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path

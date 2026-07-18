"""Shared DB-fixture builder and row helper for ``test_qa_full*``.

Filename omits the ``test_`` prefix so pytest does not collect it. Each split
file imports ``make_qa_db_file`` and wraps it in a local ``@pytest.fixture``
shim, then imports ``conn_with_rows`` for ``Row``-style cursor reads. This
keeps fixtures local to their consumer files (so future moves do not pull
surprise dependencies) while sharing the verbose schema DDL and supporting
seed data.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_core.domain import qa
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import init_test_db


_QA_SUPPORT_SCHEMA = """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL DEFAULT '',
        public_item_prefix TEXT NOT NULL DEFAULT 'YOK'
    );
    INSERT INTO projects (id, slug, name)
    VALUES (1, 'yoke', 'yoke');
    INSERT INTO projects (id, slug, name)
    VALUES (2, 'externalwebapp', 'externalwebapp');

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'issue',
        status TEXT NOT NULL DEFAULT 'idea',
        priority TEXT NOT NULL DEFAULT 'medium',
        project_id INTEGER NOT NULL DEFAULT 1,
        project_sequence INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '2'
    );
    INSERT INTO items (id, title, status, project_id, project_sequence, created_at, updated_at)
    VALUES (100, 'Test item', 'implementing', 1, 100, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z');
    INSERT INTO items (id, title, status, project_id, project_sequence, created_at, updated_at)
    VALUES (200, 'Another item', 'implementing', 1, 200, '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z');

    CREATE TABLE IF NOT EXISTS epic_tasks (
        id INTEGER PRIMARY KEY,
        epic_id INTEGER NOT NULL,
        task_num INTEGER NOT NULL,
        title TEXT,
        status TEXT DEFAULT 'planning',
        body TEXT,
        dependencies TEXT,
        UNIQUE(epic_id, task_num)
    );
    INSERT INTO epic_tasks (epic_id, task_num, title) VALUES (50, 1, 'Task 1');
"""


def _apply_qa_full_schema() -> None:
    """``apply_schema`` strategy: support tables + QA schema via the factory.

    Applies ``_QA_SUPPORT_SCHEMA`` (projects/items/epic_tasks seeds) then
    ``qa.cmd_init``, one native statement at a time through the canonical
    schema-script executor.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _QA_SUPPORT_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    qa.cmd_init()


@contextlib.contextmanager
def make_qa_db_file(tmp_path: Path):
    """Yield a backend-aware DB token with QA schema plus supporting tables.

    Seeds minimal ``projects``, ``items``, and ``epic_tasks`` rows the QA
    suites expect, then runs ``qa.cmd_init``. Delegates to the ``file_test_db``
    seam, which mints a disposable per-test Postgres database (dropped on
    exit). Used as a context manager:
    ``with make_qa_db_file(tmp_path) as db_path:``.
    """
    with init_test_db(tmp_path, apply_schema=_apply_qa_full_schema) as db_path:
        yield db_path


def conn_with_rows(db_path: str):
    """Open a backend-aware connection yielding Row-style rows.

    Returns the native psycopg connection family (name- and index-addressable
    rows) against the repointed DSN; ``db_path`` is an ignored compatibility
    token.
    """
    from yoke_core.domain import db_backend

    return db_backend.connect(db_path)


__all__ = [
    "make_qa_db_file",
    "conn_with_rows",
    "Path",
]

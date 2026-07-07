"""Shared minimal-schema ``apply_schema`` strategy for merge-audit tests.

The merge-audit report tests (``test_merge_audit.py``,
``test_merge_audit_full.py``, ``test_merge_audit_full_extras.py``) all create a
small DB with the three tables ``merge_audit.generate_report`` reads:
``items``, ``epic_tasks``, and ``epic_simulations``. Because
``generate_report`` connects through the backend factory, the schema and seed
must land in the same Postgres authority as the read. This module owns the one
DDL definition and the zero-arg ``apply_schema`` strategy those fixtures hand to
``file_test_db.init_test_db``, so the DDL is not duplicated across the three
test files.
"""

from __future__ import annotations

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

MERGE_AUDIT_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idea'
);
CREATE TABLE IF NOT EXISTS epic_tasks (
    epic_id INTEGER NOT NULL,
    task_num INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    worktree TEXT DEFAULT NULL,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE IF NOT EXISTS epic_simulations (
    id INTEGER PRIMARY KEY,
    epic_id INTEGER NOT NULL,
    phase TEXT NOT NULL,
    result TEXT,
    created_at TEXT
);
"""


def apply_merge_audit_schema() -> None:
    """``apply_schema`` strategy applying :data:`MERGE_AUDIT_SCHEMA_DDL`.

    Resolves its connection through the backend factory, satisfying
    :func:`runtime.api.fixtures.file_test_db.init_test_db`'s zero-arg
    ``apply_schema`` contract. Merge-audit tests exercise the Postgres-backed
    authority directly.
    """
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        apply_fixture_ddl(conn, MERGE_AUDIT_SCHEMA_DDL)
    finally:
        conn.close()


__all__ = ["MERGE_AUDIT_SCHEMA_DDL", "apply_merge_audit_schema"]

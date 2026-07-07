"""Shared schema and helpers for ``test_qa_gate_summary`` siblings.

Pulled out of the test module to keep the test file under the 350-line
authored-file cap.

Backend-aware: the family-local schema is applied through the
``file_test_db`` seam so the same fixtures run on SQLite (a real file under
``tmp_path``) and Postgres (a disposable per-test database, dropped on exit).
Postgres test runs select authority through ``YOKE_PG_DSN``.
"""

from __future__ import annotations

from typing import Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_SUMMARY_SCHEMA = """
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT DEFAULT 'explicit',
    success_policy TEXT,
    waived_at TEXT,
    created_at TEXT
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER,
    executor_type TEXT,
    qa_kind TEXT,
    verdict TEXT,
    raw_result TEXT,
    created_at TEXT
);
CREATE TABLE qa_artifacts (
    id INTEGER PRIMARY KEY,
    qa_run_id INTEGER,
    artifact_type TEXT,
    content_type TEXT,
    artifact_handle TEXT,
    metadata TEXT
);
"""

# A pre-migration DB shape: a table exists, but none of the qa_* tables do.
_PLACEHOLDER_SCHEMA = "CREATE TABLE _placeholder (id INTEGER);"


def _apply_summary_schema() -> None:
    """``apply_schema`` strategy: build the QA summary schema via the factory.

    Mirrors ``apply_fixture_schema_ddl`` but with the family-local schema.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _SUMMARY_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _apply_placeholder_schema() -> None:
    """``apply_schema`` strategy: a DB with a table but no qa_* tables.

    Exercises the pre-migration path where ``qa_requirements`` is absent.
    """
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _PLACEHOLDER_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def qa_db(tmp_path):
    """Empty DB with QA tables but no requirements (backend-aware)."""
    with init_test_db(tmp_path, apply_schema=_apply_summary_schema) as path:
        yield path


@pytest.fixture
def qa_db_no_tables(tmp_path):
    """Pre-migration DB: a table present, but no qa_* tables (backend-aware)."""
    with init_test_db(tmp_path, apply_schema=_apply_placeholder_schema) as path:
        yield path


def add_requirement(
    db_path: str,
    *,
    item_id: Optional[int] = 42,
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    qa_kind: str = "ac_verification",
    qa_phase: str = "verification",
    blocking_mode: str = "blocking",
    waived_at: Optional[str] = None,
) -> int:
    conn = connect_test_db(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO qa_requirements
              (item_id, epic_id, task_num, qa_kind, qa_phase, blocking_mode,
               waived_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (item_id, epic_id, task_num, qa_kind, qa_phase, blocking_mode,
             waived_at, "2026-05-07T00:00:00Z"),
        )
        rid = int(cursor.fetchone()[0])
        conn.commit()
        return rid
    finally:
        conn.close()


def add_run(
    db_path: str,
    req_id: int,
    *,
    verdict: str = "pass",
    executor_type: str = "agent",
    qa_kind: str = "ac_verification",
    created_at: str = "2026-05-07T01:00:00Z",
) -> int:
    conn = connect_test_db(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO qa_runs
              (qa_requirement_id, executor_type, qa_kind, verdict, created_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (req_id, executor_type, qa_kind, verdict, created_at),
        )
        rid = int(cursor.fetchone()[0])
        conn.commit()
        return rid
    finally:
        conn.close()


def add_artifact(db_path: str, run_id: int) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO qa_artifacts (qa_run_id, artifact_type, artifact_handle) "
            "VALUES (%s, 'screenshot', "
            "'{\"backend\":\"local\",\"path\":\"qa-artifacts/p/1/1/test.png\"}')",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()


def row_count(db_path: str, table: str) -> int:
    conn = connect_test_db(db_path)
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return n
    finally:
        conn.close()

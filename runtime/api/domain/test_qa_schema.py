"""QA schema native-catalog regression coverage."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import db_backend
from yoke_core.domain.qa_schema import (
    _QA_SCHEMA,
    _migrate_qa_vocab,
    _qa_requirements_structurally_stale,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

NOW = "2026-06-02T00:00:00Z"

_STALE_QA_SCHEMA = """
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL CHECK(qa_phase IN ('validation','post_deploy')),
    target_env TEXT,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT NOT NULL DEFAULT 'explicit',
    success_policy TEXT,
    capability_requirements TEXT,
    suite_id TEXT,
    waived_at TEXT,
    waiver_rationale TEXT,
    waiver_source TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_kind TEXT NOT NULL
);
"""


def _apply_current_qa_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _QA_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _apply_stale_qa_schema() -> None:
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _STALE_QA_SCHEMA)
        conn.execute(
            "INSERT INTO qa_requirements "
            "(id, item_id, qa_kind, qa_phase, created_at) "
            "VALUES (1, 42, 'review', 'validation', %s)",
            (NOW,),
        )
        conn.execute("INSERT INTO qa_runs (id, qa_kind) VALUES (1, 'review')")
        conn.commit()
    finally:
        conn.close()


def test_current_qa_phase_constraint_is_not_stale(tmp_path: Path) -> None:
    with init_test_db(tmp_path, apply_schema=_apply_current_qa_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert not _qa_requirements_structurally_stale(conn)
        finally:
            conn.close()


def test_migrate_qa_vocab_refreshes_stale_constraint(tmp_path: Path) -> None:
    with init_test_db(tmp_path, apply_schema=_apply_stale_qa_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            assert _qa_requirements_structurally_stale(conn)

            _migrate_qa_vocab(conn)

            assert not _qa_requirements_structurally_stale(conn)
            row = conn.execute(
                "SELECT qa_kind, qa_phase FROM qa_requirements WHERE id=1"
            ).fetchone()
            assert tuple(row) == ("implementation_review", "verification")
        finally:
            conn.close()

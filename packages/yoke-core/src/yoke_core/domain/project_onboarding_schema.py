"""Native schema declarations for project onboarding checklist runs."""

from __future__ import annotations

from typing import Any
from yoke_core.domain import db_backend

PROJECT_ONBOARDING_RUNS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS project_onboarding_runs (
    run_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    project_id INTEGER,
    branch TEXT NOT NULL,
    checkout_path TEXT,
    machine_config_path TEXT,
    github_repo TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
)
"""

PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL = (
    "FOREIGN KEY (run_id) REFERENCES project_onboarding_runs(run_id)"
)

PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS project_onboarding_checklist_rows (
    run_id TEXT NOT NULL,
    row_id TEXT NOT NULL,
    step TEXT NOT NULL,
    title TEXT NOT NULL,
    layer TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    hint TEXT,
    evidence_json TEXT NOT NULL,
    blocker TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, row_id),
    {PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL}
)
"""


def _ensure_columns(conn: Any) -> None:
    row_columns = {
        "evidence_json": "TEXT NOT NULL DEFAULT '{}'",
        "blocker": "TEXT NOT NULL DEFAULT ''",
        "note": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in row_columns.items():
        _ensure_column(conn, "project_onboarding_checklist_rows", column, definition)


def _ensure_column(conn: Any, table: str, column: str, definition: str) -> None:
    if _column_exists(conn, table, column):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _column_exists(conn: Any, table: str, column: str) -> bool:
    if db_backend.connection_is_postgres(conn):
        p = _p(conn)
        return (
            conn.execute(
                "SELECT 1 FROM information_schema.columns "
                f"WHERE table_name = {p} AND column_name = {p}",
                (table, column),
            ).fetchone()
            is not None
        )
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(_column_name(row) == column for row in rows)


def _column_name(row: Any) -> str:
    return row["name"] if hasattr(row, "keys") else row[1]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"

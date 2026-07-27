"""Portable schema support for registered-command validation tests."""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.projects_restart_schema import _projects_table_sql
from yoke_core.domain.schema_init_apply import execute_schema_script


def apply_command_plan_schema() -> None:
    """Create the project and QA-plan tables used by the validator."""
    conn = db_backend.connect()
    try:
        execute_schema_script(conn, _projects_table_sql(if_not_exists=False))
        execute_schema_script(
            conn,
            """
            CREATE TABLE qa_plans (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                slug TEXT NOT NULL,
                retired_at TEXT
            );
            CREATE TABLE qa_plan_cases (
                id INTEGER PRIMARY KEY,
                plan_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                method_id TEXT NOT NULL,
                method_config TEXT NOT NULL
            );
            """,
        )
        conn.commit()
    finally:
        conn.close()


__all__ = ["apply_command_plan_schema"]

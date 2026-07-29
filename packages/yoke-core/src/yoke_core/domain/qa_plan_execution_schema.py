"""Durable schema authority for ordered QA plan execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


QA_PLAN_EXECUTION_TABLE = "qa_plan_executions"
QA_PLAN_EXECUTION_RESULT_TABLE = "qa_plan_execution_results"

QA_PLAN_EXECUTION_COLUMNS = (
    "id",
    "item_id",
    "deployment_run_id",
    "transition_id",
    "actor_id",
    "session_id",
    "roster_digest",
    "roster_json",
    "cursor_ordinal",
    "state",
    "machine_lease_id",
    "created_at",
    "heartbeat_at",
    "completed_at",
    "release_reason",
)
QA_PLAN_EXECUTION_TARGET_COLUMNS = (
    "execution_target_json",
    "execution_target_digest",
)
QA_PLAN_EXECUTION_RESULT_COLUMNS = (
    "execution_id",
    "ordinal",
    "requirement_id",
    "result_json",
    "completed_at",
)
QA_PLAN_EXECUTION_INDEXES = (
    (QA_PLAN_EXECUTION_TABLE, "idx_qa_plan_executions_active"),
    (
        QA_PLAN_EXECUTION_TABLE,
        "idx_qa_plan_executions_deployment_active",
    ),
    (
        QA_PLAN_EXECUTION_RESULT_TABLE,
        "idx_qa_plan_execution_results_requirement",
    ),
)

_QA_PLAN_EXECUTION_FOREIGN_KEYS = """,
    FOREIGN KEY (execution_id) REFERENCES qa_plan_executions(id),
    FOREIGN KEY (requirement_id) REFERENCES qa_requirements(id)"""

QA_PLAN_EXECUTION_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS qa_plan_executions (
    id TEXT PRIMARY KEY,
    item_id INTEGER,
    deployment_run_id TEXT,
    transition_id TEXT,
    actor_id TEXT,
    session_id TEXT NOT NULL,
    roster_digest TEXT NOT NULL,
    roster_json TEXT NOT NULL,
    execution_target_json TEXT,
    execution_target_digest TEXT,
    cursor_ordinal INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN (
        'active','waiting','awaiting_agent_review','completed','aborted','error'
    )),
    machine_lease_id INTEGER,
    created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    completed_at TEXT,
    release_reason TEXT,
    CHECK (
        (item_id IS NOT NULL AND deployment_run_id IS NULL
            AND transition_id IS NOT NULL) OR
        (item_id IS NULL AND deployment_run_id IS NOT NULL
            AND transition_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_executions_active
    ON qa_plan_executions(item_id, transition_id)
    WHERE item_id IS NOT NULL
        AND state IN ('active','waiting','awaiting_agent_review');
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_executions_deployment_active
    ON qa_plan_executions(deployment_run_id)
    WHERE deployment_run_id IS NOT NULL
        AND state IN ('active','waiting','awaiting_agent_review');

CREATE TABLE IF NOT EXISTS qa_plan_execution_results (
    execution_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    requirement_id INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY(execution_id, ordinal){_QA_PLAN_EXECUTION_FOREIGN_KEYS}
);
CREATE INDEX IF NOT EXISTS idx_qa_plan_execution_results_requirement
    ON qa_plan_execution_results(requirement_id);
"""


def qa_plan_execution_schema_sql(*, include_foreign_keys: bool = True) -> str:
    """Return the canonical DDL, optionally omitting fixture-only references."""
    if include_foreign_keys:
        return QA_PLAN_EXECUTION_SCHEMA_SQL
    return QA_PLAN_EXECUTION_SCHEMA_SQL.replace(
        _QA_PLAN_EXECUTION_FOREIGN_KEYS,
        "",
    )


def converge_qa_plan_execution_schema(conn: Any) -> None:
    """Create ordered-plan execution records without committing the caller."""
    if not _table_exists(conn, "qa_requirements"):
        raise RuntimeError(
            "QA plan execution records require the deployed qa_requirements table"
        )
    if _table_exists(conn, QA_PLAN_EXECUTION_TABLE):
        from yoke_core.domain import db_backend

        if db_backend.connection_is_postgres(conn):
            from yoke_core.domain.migrations.qa_plan_execution_deployment_subject import (
                apply as expand_deployment_subject,
                invariants as assert_deployment_subject,
            )

            try:
                assert_deployment_subject(conn)
            except AssertionError:
                expand_deployment_subject(conn)
        for column in QA_PLAN_EXECUTION_TARGET_COLUMNS:
            if not _column_exists(conn, QA_PLAN_EXECUTION_TABLE, column):
                conn.execute(
                    f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} "
                    f"ADD COLUMN {column} TEXT"
                )
    execute_schema_script(conn, QA_PLAN_EXECUTION_SCHEMA_SQL)


def assert_qa_plan_execution_schema_invariants(conn: Any) -> None:
    """Require both execution tables, their columns, and lookup indexes."""
    table_columns = (
        (
            QA_PLAN_EXECUTION_TABLE,
            QA_PLAN_EXECUTION_COLUMNS + QA_PLAN_EXECUTION_TARGET_COLUMNS,
        ),
        (QA_PLAN_EXECUTION_RESULT_TABLE, QA_PLAN_EXECUTION_RESULT_COLUMNS),
    )
    missing_tables = [
        table for table, _columns in table_columns if not _table_exists(conn, table)
    ]
    if missing_tables:
        raise AssertionError(
            "QA plan execution tables are missing: " + ", ".join(missing_tables)
        )
    missing_columns = [
        f"{table}.{column}"
        for table, columns in table_columns
        for column in columns
        if not _column_exists(conn, table, column)
    ]
    if missing_columns:
        raise AssertionError(
            "QA plan execution columns are missing: " + ", ".join(missing_columns)
        )
    missing_indexes = [
        index
        for table, index in QA_PLAN_EXECUTION_INDEXES
        if not _index_exists(conn, index, table)
    ]
    if missing_indexes:
        raise AssertionError(
            "QA plan execution indexes are missing: " + ", ".join(missing_indexes)
        )


__all__ = [
    "QA_PLAN_EXECUTION_COLUMNS",
    "QA_PLAN_EXECUTION_INDEXES",
    "QA_PLAN_EXECUTION_RESULT_COLUMNS",
    "QA_PLAN_EXECUTION_RESULT_TABLE",
    "QA_PLAN_EXECUTION_SCHEMA_SQL",
    "QA_PLAN_EXECUTION_TABLE",
    "QA_PLAN_EXECUTION_TARGET_COLUMNS",
    "assert_qa_plan_execution_schema_invariants",
    "converge_qa_plan_execution_schema",
    "qa_plan_execution_schema_sql",
]

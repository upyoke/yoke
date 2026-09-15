"""Durable schema authority for ordered QA plan execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_deployment_scope_schema import (
    DEPLOYMENT_SCOPE_COLUMNS,
    EXECUTION_SCOPE_INDEX_NAMES,
    EXECUTION_SCOPE_INDEX_SQL,
    EXECUTION_SUBJECT_CONSTRAINT,
    EXECUTION_SUBJECT_EXPRESSION,
    LIVE_EXECUTION_STATES,
    add_deployment_scope_columns,
    assert_deployment_scope_contract,
)
from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


QA_PLAN_EXECUTION_TABLE = "qa_plan_executions"
QA_PLAN_EXECUTION_RESULT_TABLE = "qa_plan_execution_results"
LIVE_PLAN_EXECUTION_STATES = LIVE_EXECUTION_STATES
TERMINAL_PLAN_EXECUTION_STATES = frozenset({"completed", "aborted", "error"})
LIVE_PLAN_EXECUTION_SQL = ", ".join(map(repr, sorted(LIVE_PLAN_EXECUTION_STATES)))


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
#: Set on an execution that resumes a walk a prior execution left behind.
#: Its presence is the whole contract: the host keeps the state the prior
#: execution built, so no case in this execution reaches a host baseline.
QA_PLAN_EXECUTION_CONTINUATION_COLUMNS = ("continues_execution_id",)
QA_PLAN_EXECUTION_ADDITIVE_COLUMNS = (
    QA_PLAN_EXECUTION_TARGET_COLUMNS
    + QA_PLAN_EXECUTION_CONTINUATION_COLUMNS
    + tuple(column for column, _definition in DEPLOYMENT_SCOPE_COLUMNS)
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
    *((QA_PLAN_EXECUTION_TABLE, name) for name in EXECUTION_SCOPE_INDEX_NAMES),
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
    continues_execution_id TEXT,
    cursor_ordinal INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL CHECK(state IN (
        'active','waiting','awaiting_agent_review','completed','aborted','error'
    )),
    machine_lease_id INTEGER,
    created_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    completed_at TEXT,
    release_reason TEXT,
    deployment_stage TEXT,
    deployment_member_item_id INTEGER,
    CONSTRAINT {EXECUTION_SUBJECT_CONSTRAINT}
        CHECK ({EXECUTION_SUBJECT_EXPRESSION})
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_executions_active
    ON qa_plan_executions(item_id, transition_id)
    WHERE item_id IS NOT NULL
        AND state IN ('active','waiting','awaiting_agent_review');
{EXECUTION_SCOPE_INDEX_SQL}

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
        for column in QA_PLAN_EXECUTION_ADDITIVE_COLUMNS:
            if not _column_exists(conn, QA_PLAN_EXECUTION_TABLE, column):
                definition = dict(DEPLOYMENT_SCOPE_COLUMNS).get(column, "TEXT")
                conn.execute(
                    f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} "
                    f"ADD COLUMN {column} {definition}"
                )
        add_deployment_scope_columns(conn)
    execute_schema_script(conn, QA_PLAN_EXECUTION_SCHEMA_SQL)


def converge_qa_plan_execution_subject_schema(conn: Any) -> None:
    """Add selectors only; ordered history owns the breaking cutover."""
    add_deployment_scope_columns(conn)


def assert_qa_plan_execution_subject_invariants(conn: Any) -> None:
    """Require the complete deployment-scoped subject contract."""
    assert_deployment_scope_contract(conn)


def assert_qa_plan_execution_schema_invariants(conn: Any) -> None:
    """Require both execution tables, their columns, and lookup indexes."""
    table_columns = (
        (
            QA_PLAN_EXECUTION_TABLE,
            QA_PLAN_EXECUTION_COLUMNS + QA_PLAN_EXECUTION_ADDITIVE_COLUMNS,
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
    "LIVE_PLAN_EXECUTION_SQL",
    "LIVE_PLAN_EXECUTION_STATES",
    "QA_PLAN_EXECUTION_ADDITIVE_COLUMNS",
    "QA_PLAN_EXECUTION_COLUMNS",
    "QA_PLAN_EXECUTION_CONTINUATION_COLUMNS",
    "QA_PLAN_EXECUTION_INDEXES",
    "QA_PLAN_EXECUTION_RESULT_COLUMNS",
    "QA_PLAN_EXECUTION_RESULT_TABLE",
    "QA_PLAN_EXECUTION_SCHEMA_SQL",
    "QA_PLAN_EXECUTION_TABLE",
    "QA_PLAN_EXECUTION_TARGET_COLUMNS",
    "TERMINAL_PLAN_EXECUTION_STATES",
    "assert_qa_plan_execution_schema_invariants",
    "assert_qa_plan_execution_subject_invariants",
    "converge_qa_plan_execution_schema",
    "converge_qa_plan_execution_subject_schema",
    "qa_plan_execution_schema_sql",
]

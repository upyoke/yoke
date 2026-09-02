"""Durable schema authority for ordered QA plan execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _column_exists,
    _get_check_constraint_defs,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.schema_init_apply import execute_schema_script


QA_PLAN_EXECUTION_TABLE = "qa_plan_executions"
QA_PLAN_EXECUTION_RESULT_TABLE = "qa_plan_execution_results"
_QA_PLAN_EXECUTION_SUBJECT_CHECK = "qa_plan_executions_subject_check"

LIVE_PLAN_EXECUTION_STATES = frozenset({"active", "waiting", "awaiting_agent_review"})
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
    QA_PLAN_EXECUTION_TARGET_COLUMNS + QA_PLAN_EXECUTION_CONTINUATION_COLUMNS
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
        if db_backend.connection_is_postgres(conn):
            try:
                assert_qa_plan_execution_subject_invariants(conn)
            except AssertionError:
                converge_qa_plan_execution_subject_schema(conn)
        for column in QA_PLAN_EXECUTION_ADDITIVE_COLUMNS:
            if not _column_exists(conn, QA_PLAN_EXECUTION_TABLE, column):
                conn.execute(
                    f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} ADD COLUMN {column} TEXT"
                )
    execute_schema_script(conn, QA_PLAN_EXECUTION_SCHEMA_SQL)


def converge_qa_plan_execution_subject_schema(conn: Any) -> None:
    """Allow a plan execution to belong to an item or a deployment run."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("QA plan execution subjects require Postgres authority")
    required = (QA_PLAN_EXECUTION_TABLE, "deployment_runs")
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA plan execution subjects require deployed tables: " + ", ".join(missing)
        )
    if not _column_exists(conn, QA_PLAN_EXECUTION_TABLE, "deployment_run_id"):
        conn.execute(
            f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} ADD COLUMN deployment_run_id TEXT"
        )
    conn.execute(
        f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} ALTER COLUMN item_id DROP NOT NULL"
    )
    conn.execute(
        f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} "
        "ALTER COLUMN transition_id DROP NOT NULL"
    )
    row = conn.execute(
        "SELECT 1 FROM pg_constraint "
        f"WHERE conrelid='{QA_PLAN_EXECUTION_TABLE}'::regclass "
        "AND conname=%s",
        (_QA_PLAN_EXECUTION_SUBJECT_CHECK,),
    ).fetchone()
    if row is None:
        conn.execute(
            f"ALTER TABLE {QA_PLAN_EXECUTION_TABLE} "
            f"ADD CONSTRAINT {_QA_PLAN_EXECUTION_SUBJECT_CHECK} CHECK ("
            "(item_id IS NOT NULL AND deployment_run_id IS NULL "
            "AND transition_id IS NOT NULL) OR "
            "(item_id IS NULL AND deployment_run_id IS NOT NULL "
            "AND transition_id IS NULL))"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_qa_plan_executions_deployment_active "
        f"ON {QA_PLAN_EXECUTION_TABLE}(deployment_run_id) "
        "WHERE deployment_run_id IS NOT NULL "
        "AND state IN ('active','waiting')"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_qa_requirement_deployment_materialization "
        "ON qa_requirements("
        "deployment_run_id, plan_id, plan_case_key, "
        "COALESCE(host_baseline, '')"
        ") WHERE deployment_run_id IS NOT NULL AND plan_id IS NOT NULL"
    )


def assert_qa_plan_execution_subject_invariants(conn: Any) -> None:
    """Require the item-or-deployment-run subject contract."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("QA plan execution subjects require Postgres authority")
    if not _column_exists(conn, QA_PLAN_EXECUTION_TABLE, "deployment_run_id"):
        raise AssertionError("qa_plan_executions.deployment_run_id is missing")
    nullability = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT column_name,is_nullable FROM information_schema.columns "
            "WHERE table_schema=current_schema() "
            f"AND table_name='{QA_PLAN_EXECUTION_TABLE}' "
            "AND column_name IN ('item_id','transition_id')"
        ).fetchall()
    }
    if nullability != {"item_id": "YES", "transition_id": "YES"}:
        raise AssertionError(
            "QA plan execution item and transition columns must be nullable"
        )
    checks = _get_check_constraint_defs(conn, QA_PLAN_EXECUTION_TABLE)
    if not any(
        "deployment_run_id" in definition
        and "item_id" in definition
        and "transition_id" in definition
        for definition in checks
    ):
        raise AssertionError(
            "QA plan executions lack the item-or-deployment-run subject check"
        )
    required_indexes = (
        (
            "idx_qa_plan_executions_deployment_active",
            QA_PLAN_EXECUTION_TABLE,
        ),
        ("idx_qa_requirement_deployment_materialization", "qa_requirements"),
    )
    missing_indexes = [
        index
        for index, table in required_indexes
        if not _index_exists(conn, index, table)
    ]
    if missing_indexes:
        raise AssertionError(
            "QA plan execution subject indexes are missing: "
            + ", ".join(missing_indexes)
        )


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

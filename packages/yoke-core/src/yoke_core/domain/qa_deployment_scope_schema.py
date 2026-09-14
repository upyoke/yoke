"""Database contract for deployment-stage and member-scoped QA."""

from __future__ import annotations

import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _add_column_if_not_exists,
    _column_exists,
    _table_exists,
)


DEPLOYMENT_STAGE_COLUMN = "deployment_stage"
DEPLOYMENT_MEMBER_COLUMN = "deployment_member_item_id"
DEPLOYMENT_SCOPE_COLUMNS = (
    (DEPLOYMENT_STAGE_COLUMN, "TEXT"),
    (DEPLOYMENT_MEMBER_COLUMN, "INTEGER"),
)

LIVE_EXECUTION_STATES = frozenset({"active", "waiting", "awaiting_agent_review"})
LIVE_EXECUTION_STATE_SQL = ",".join(
    f"'{state}'" for state in sorted(LIVE_EXECUTION_STATES)
)

EXECUTION_SUBJECT_CONSTRAINT = "qa_plan_executions_subject_check"
REQUIREMENT_SUBJECT_CONSTRAINT = "qa_requirements_subject_check"

EXECUTION_SUBJECT_EXPRESSION = """
(
    item_id IS NOT NULL AND deployment_run_id IS NULL
    AND transition_id IS NOT NULL
    AND deployment_stage IS NULL AND deployment_member_item_id IS NULL
) OR (
    item_id IS NULL AND deployment_run_id IS NOT NULL
    AND transition_id IS NULL
    AND (
        (deployment_stage IS NULL AND deployment_member_item_id IS NULL) OR
        (deployment_stage IS NOT NULL)
    )
)
""".strip()

REQUIREMENT_SUBJECT_EXPRESSION = """
(
    item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL
    AND deployment_run_id IS NULL
    AND deployment_stage IS NULL AND deployment_member_item_id IS NULL
) OR (
    item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL
    AND deployment_run_id IS NULL
    AND deployment_stage IS NULL AND deployment_member_item_id IS NULL
) OR (
    item_id IS NULL AND epic_id IS NULL AND task_num IS NULL
    AND deployment_run_id IS NOT NULL
    AND (
        (deployment_stage IS NULL AND deployment_member_item_id IS NULL) OR
        (deployment_stage IS NOT NULL)
    )
)
""".strip()

_EXECUTION_INDEX_SPECS = (
    (
        "idx_qa_plan_executions_deployment_legacy_active",
        ("deployment_run_id",),
        "deployment_run_id IS NOT NULL AND deployment_stage IS NULL "
        "AND deployment_member_item_id IS NULL",
    ),
    (
        "idx_qa_plan_executions_deployment_stage_active",
        ("deployment_run_id", "deployment_stage"),
        "deployment_run_id IS NOT NULL AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL",
    ),
    (
        "idx_qa_plan_executions_deployment_member_stage_active",
        ("deployment_run_id", "deployment_stage", "deployment_member_item_id"),
        "deployment_run_id IS NOT NULL AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NOT NULL",
    ),
)

_REQUIREMENT_INDEX_SPECS = tuple(
    (
        requirement_name,
        execution_spec[1] + ("plan_id", "plan_case_key", "COALESCE(host_baseline, '')"),
        execution_spec[2] + " AND plan_id IS NOT NULL",
    )
    for requirement_name, execution_spec in zip(
        (
            "idx_qa_requirement_deployment_legacy_materialization",
            "idx_qa_requirement_deployment_stage_materialization",
            "idx_qa_requirement_deployment_member_stage_materialization",
        ),
        _EXECUTION_INDEX_SPECS,
    )
)


def _index_sql(table: str, specs: tuple[tuple[str, tuple[str, ...], str], ...]) -> str:
    statements = []
    for name, keys, predicate in specs:
        statements.append(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}"
            f"({', '.join(keys)}) WHERE {predicate} "
            f"AND state IN ({LIVE_EXECUTION_STATE_SQL})"
            if table == "qa_plan_executions"
            else f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}"
            f"({', '.join(keys)}) WHERE {predicate}"
        )
    return ";\n".join(statements) + ";"


EXECUTION_SCOPE_INDEX_SQL = _index_sql("qa_plan_executions", _EXECUTION_INDEX_SPECS)
REQUIREMENT_SCOPE_INDEX_SQL = _index_sql("qa_requirements", _REQUIREMENT_INDEX_SPECS)
EXECUTION_SCOPE_INDEX_NAMES = tuple(spec[0] for spec in _EXECUTION_INDEX_SPECS)
REQUIREMENT_SCOPE_INDEX_NAMES = tuple(spec[0] for spec in _REQUIREMENT_INDEX_SPECS)


def add_deployment_scope_columns(conn: Any) -> None:
    """Add nullable scope selectors without changing existing subjects."""
    if _table_exists(conn, "qa_plan_executions"):
        _add_column_if_not_exists(
            conn, "qa_plan_executions", "deployment_run_id", "TEXT"
        )
    for table in ("qa_plan_executions", "qa_requirements"):
        if not _table_exists(conn, table):
            continue
        for column, definition in DEPLOYMENT_SCOPE_COLUMNS:
            _add_column_if_not_exists(conn, table, column, definition)


def _subject_constraints(conn: Any, table: str) -> list[str]:
    required = {
        "qa_plan_executions": ("item_id", "deployment_run_id", "transition_id"),
        "qa_requirements": ("item_id", "epic_id", "task_num", "deployment_run_id"),
    }[table]
    rows = conn.execute(
        "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
        f"WHERE conrelid='{table}'::regclass AND contype='c'"
    ).fetchall()
    return [
        str(row[0]) for row in rows if all(column in str(row[1]) for column in required)
    ]


def replace_deployment_scope_contract(conn: Any) -> None:
    """Install the breaking scoped-subject constraints and indexes."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("deployment-scoped QA requires Postgres authority")
    add_deployment_scope_columns(conn)
    if _table_exists(conn, "qa_plan_executions"):
        conn.execute(
            "ALTER TABLE qa_plan_executions ALTER COLUMN item_id DROP NOT NULL"
        )
        conn.execute(
            "ALTER TABLE qa_plan_executions ALTER COLUMN transition_id DROP NOT NULL"
        )
    table_contracts = (
        (
            "qa_plan_executions",
            EXECUTION_SUBJECT_CONSTRAINT,
            EXECUTION_SUBJECT_EXPRESSION,
            "idx_qa_plan_executions_deployment_active",
            EXECUTION_SCOPE_INDEX_SQL,
        ),
        (
            "qa_requirements",
            REQUIREMENT_SUBJECT_CONSTRAINT,
            REQUIREMENT_SUBJECT_EXPRESSION,
            "idx_qa_requirement_deployment_materialization",
            REQUIREMENT_SCOPE_INDEX_SQL,
        ),
    )
    for table, constraint, expression, obsolete_index, index_sql in table_contracts:
        if not _table_exists(conn, table):
            continue
        for existing in _subject_constraints(conn, table):
            conn.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{existing}"')
        conn.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" CHECK ({expression})'
        )
        conn.execute(f'DROP INDEX IF EXISTS "{obsolete_index}"')
        for statement in index_sql.split(";"):
            if statement.strip():
                conn.execute(statement)


def _index_contract(conn: Any, table: str, name: str) -> tuple[tuple[str, ...], str]:
    row = conn.execute(
        "SELECT ARRAY(SELECT pg_get_indexdef(i.indexrelid, key_position, true) "
        "FROM generate_series(1, i.indnkeyatts) key_position "
        "ORDER BY key_position), pg_get_expr(i.indpred, i.indrelid) "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
        "JOIN pg_class t ON t.oid=i.indrelid "
        "WHERE t.relname=%s AND c.relname=%s",
        (table, name),
    ).fetchone()
    if row is None:
        raise AssertionError(f"{name} is missing")
    return tuple(str(value) for value in row[0]), str(row[1] or "")


def _normalized_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(re.sub(r"\s+", "", key).replace("::text", "") for key in keys)


def _assert_indexes(
    conn: Any,
    table: str,
    specs: tuple[tuple[str, tuple[str, ...], str], ...],
) -> None:
    for name, expected_keys, expected_scope in specs:
        keys, predicate = _index_contract(conn, table, name)
        if _normalized_keys(keys) != _normalized_keys(expected_keys):
            raise AssertionError(f"{name} has wrong keys: {keys}")
        for token in re.findall(r"\bdeployment_[a-z_]+\b|\bplan_id\b", expected_scope):
            expected_null = f"{token} IS NULL" in expected_scope
            clause = f"{token} IS {'NULL' if expected_null else 'NOT NULL'}"
            if clause.lower() not in predicate.lower():
                raise AssertionError(
                    f"{name} lacks predicate clause {clause}: {predicate}"
                )
        if table == "qa_plan_executions":
            states = set(
                re.findall(r"'(active|waiting|awaiting_agent_review)'", predicate)
            )
            if states != LIVE_EXECUTION_STATES:
                raise AssertionError(
                    f"{name} has wrong live-state predicate: {predicate}"
                )


def assert_deployment_scope_contract(conn: Any) -> None:
    """Assert exact scoped columns, subject checks, and unique-index keys."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("deployment-scoped QA requires Postgres authority")
    for table, constraint in (
        ("qa_plan_executions", EXECUTION_SUBJECT_CONSTRAINT),
        ("qa_requirements", REQUIREMENT_SUBJECT_CONSTRAINT),
    ):
        for column, _definition in DEPLOYMENT_SCOPE_COLUMNS:
            if not _column_exists(conn, table, column):
                raise AssertionError(f"{table}.{column} is missing")
        names = _subject_constraints(conn, table)
        if names != [constraint]:
            raise AssertionError(f"{table} has wrong subject constraints: {names}")
    _assert_indexes(conn, "qa_plan_executions", _EXECUTION_INDEX_SPECS)
    _assert_indexes(conn, "qa_requirements", _REQUIREMENT_INDEX_SPECS)


__all__ = [
    "DEPLOYMENT_MEMBER_COLUMN",
    "DEPLOYMENT_SCOPE_COLUMNS",
    "DEPLOYMENT_STAGE_COLUMN",
    "EXECUTION_SCOPE_INDEX_NAMES",
    "EXECUTION_SCOPE_INDEX_SQL",
    "EXECUTION_SUBJECT_CONSTRAINT",
    "EXECUTION_SUBJECT_EXPRESSION",
    "LIVE_EXECUTION_STATES",
    "LIVE_EXECUTION_STATE_SQL",
    "REQUIREMENT_SCOPE_INDEX_NAMES",
    "REQUIREMENT_SCOPE_INDEX_SQL",
    "REQUIREMENT_SUBJECT_CONSTRAINT",
    "REQUIREMENT_SUBJECT_EXPRESSION",
    "add_deployment_scope_columns",
    "assert_deployment_scope_contract",
    "replace_deployment_scope_contract",
]

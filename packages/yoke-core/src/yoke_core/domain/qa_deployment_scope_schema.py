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
from yoke_core.domain.sql_boolean_contract import canonical_boolean_expression


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

LEGACY_EXECUTION_SUBJECT_EXPRESSION = """
(item_id IS NOT NULL AND deployment_run_id IS NULL AND transition_id IS NOT NULL)
OR (item_id IS NULL AND deployment_run_id IS NOT NULL AND transition_id IS NULL)
""".strip()

LEGACY_REQUIREMENT_SUBJECT_EXPRESSION = """
(item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NULL)
OR (item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL AND deployment_run_id IS NULL)
OR (item_id IS NULL AND epic_id IS NULL AND task_num IS NULL AND deployment_run_id IS NOT NULL)
""".strip()

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
        (deployment_stage IS NOT NULL AND TRIM(deployment_stage) <> '')
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
        (deployment_stage IS NOT NULL AND TRIM(deployment_stage) <> '')
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
        execution_spec[1]
        + ("plan_id", "plan_case_key", "COALESCE(host_baseline, '')")
        + (() if position == 0 else ("execution_target_digest",)),
        execution_spec[2] + " AND plan_id IS NOT NULL",
    )
    for position, (requirement_name, execution_spec) in enumerate(
        zip(
            (
                "idx_qa_requirement_deployment_legacy_materialization",
                "idx_qa_requirement_deployment_stage_materialization",
                "idx_qa_requirement_deployment_member_stage_materialization",
            ),
            _EXECUTION_INDEX_SPECS,
        )
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


def _canonical_sql(value: str) -> Any:
    return canonical_boolean_expression(value)


def _subject_constraints(conn: Any, table: str) -> list[str]:
    required = {
        "qa_plan_executions": ("item_id", "deployment_run_id", "transition_id"),
        "qa_requirements": ("item_id", "epic_id", "task_num", "deployment_run_id"),
    }[table]
    rows = conn.execute(
        "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
        f"WHERE conrelid='{table}'::regclass AND contype='c' ORDER BY conname"
    ).fetchall()
    candidates = [row for row in rows if all(column in str(row[1]) for column in required)]
    legacy = {
        "qa_plan_executions": LEGACY_EXECUTION_SUBJECT_EXPRESSION,
        "qa_requirements": LEGACY_REQUIREMENT_SUBJECT_EXPRESSION,
    }[table]
    current = {
        "qa_plan_executions": EXECUTION_SUBJECT_EXPRESSION,
        "qa_requirements": REQUIREMENT_SUBJECT_EXPRESSION,
    }[table]
    supported = {_canonical_sql(f"CHECK ({value})") for value in (legacy, current)}
    unknown = [
        (str(row[0]), str(row[1]))
        for row in candidates
        if _canonical_sql(str(row[1])) not in supported
    ]
    if unknown:
        raise RuntimeError(
            f"{table} has unrecognized subject checks {unknown}; refusing to drop "
            "them. Recovery: classify and replace the checks in an ordered migration."
        )
    return [str(row[0]) for row in candidates]


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


def _index_contract(
    conn: Any, table: str, name: str
) -> tuple[tuple[str, ...], str, bool, bool, bool]:
    row = conn.execute(
        "SELECT ARRAY(SELECT pg_get_indexdef(i.indexrelid, key_position, true) "
        "FROM generate_series(1, i.indnkeyatts) key_position "
        "ORDER BY key_position), pg_get_expr(i.indpred, i.indrelid), "
        "i.indisunique,i.indisvalid,i.indisready "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
        "JOIN pg_class t ON t.oid=i.indrelid "
        "WHERE t.relname=%s AND c.relname=%s",
        (table, name),
    ).fetchone()
    if row is None:
        raise AssertionError(f"{name} is missing")
    return (
        tuple(str(value) for value in row[0]),
        str(row[1] or ""),
        bool(row[2]),
        bool(row[3]),
        bool(row[4]),
    )


def _normalized_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(re.sub(r"\s+", "", key).replace("::text", "") for key in keys)


def _assert_indexes(
    conn: Any,
    table: str,
    specs: tuple[tuple[str, tuple[str, ...], str], ...],
) -> None:
    for name, expected_keys, expected_scope in specs:
        keys, predicate, unique, valid, ready = _index_contract(conn, table, name)
        if not unique or not valid or not ready:
            raise AssertionError(
                f"{name} must be unique, valid, and ready; got "
                f"unique={unique}, valid={valid}, ready={ready}"
            )
        if _normalized_keys(keys) != _normalized_keys(expected_keys):
            raise AssertionError(f"{name} has wrong keys: {keys}")
        expected_predicate = expected_scope
        if table == "qa_plan_executions":
            expected_predicate += (
                f" AND state = ANY (ARRAY[{LIVE_EXECUTION_STATE_SQL}])"
            )
        if _canonical_sql(predicate) != _canonical_sql(expected_predicate):
            raise AssertionError(
                f"{name} has wrong predicate: {predicate}; expected {expected_predicate}"
            )


def assert_deployment_scope_contract(conn: Any) -> None:
    """Assert exact scoped columns, subject checks, and unique-index keys."""
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("deployment-scoped QA requires Postgres authority")
    for table, constraint, expression in (
        (
            "qa_plan_executions",
            EXECUTION_SUBJECT_CONSTRAINT,
            EXECUTION_SUBJECT_EXPRESSION,
        ),
        (
            "qa_requirements",
            REQUIREMENT_SUBJECT_CONSTRAINT,
            REQUIREMENT_SUBJECT_EXPRESSION,
        ),
    ):
        for column, _definition in DEPLOYMENT_SCOPE_COLUMNS:
            if not _column_exists(conn, table, column):
                raise AssertionError(f"{table}.{column} is missing")
        names = _subject_constraints(conn, table)
        if names != [constraint]:
            raise AssertionError(f"{table} has wrong subject constraints: {names}")
        row = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid=%s::regclass AND conname=%s",
            (table, constraint),
        ).fetchone()
        if row is None or _canonical_sql(str(row[0])) != _canonical_sql(
            f"CHECK ({expression})"
        ):
            raise AssertionError(f"{constraint} does not match the scoped subject contract")
    _assert_indexes(conn, "qa_plan_executions", _EXECUTION_INDEX_SPECS)
    _assert_indexes(conn, "qa_requirements", _REQUIREMENT_INDEX_SPECS)
    for obsolete in (
        "idx_qa_plan_executions_deployment_active",
        "idx_qa_requirement_deployment_materialization",
    ):
        if conn.execute("SELECT to_regclass(%s)", (obsolete,)).fetchone()[0] is not None:
            raise AssertionError(f"obsolete index {obsolete} still exists")


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
    "LEGACY_EXECUTION_SUBJECT_EXPRESSION",
    "LEGACY_REQUIREMENT_SUBJECT_EXPRESSION",
    "REQUIREMENT_SCOPE_INDEX_NAMES",
    "REQUIREMENT_SCOPE_INDEX_SQL",
    "REQUIREMENT_SUBJECT_CONSTRAINT",
    "REQUIREMENT_SUBJECT_EXPRESSION",
    "add_deployment_scope_columns",
    "assert_deployment_scope_contract",
    "replace_deployment_scope_contract",
]

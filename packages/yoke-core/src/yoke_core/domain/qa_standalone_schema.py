"""Exclusive standalone ownership in the existing QA execution records."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_deployment_scope_schema import (
    EXECUTION_SUBJECT_EXPRESSION as DEPLOYMENT_EXECUTION_EXPRESSION,
    REQUIREMENT_SUBJECT_EXPRESSION as DEPLOYMENT_REQUIREMENT_EXPRESSION,
    EXECUTION_SUBJECT_CONSTRAINT,
    REQUIREMENT_SUBJECT_CONSTRAINT,
    LIVE_EXECUTION_STATE_SQL,
)
from yoke_core.domain.schema_common import _add_column_if_not_exists, _table_exists
from yoke_core.domain.sql_boolean_contract import canonical_boolean_expression


EXECUTION_SUBJECT_EXPRESSION = f"""(standalone_plan_id IS NULL AND ({DEPLOYMENT_EXECUTION_EXPRESSION})) OR (
    standalone_plan_id IS NOT NULL AND item_id IS NULL
    AND deployment_run_id IS NULL AND transition_id IS NULL
    AND deployment_stage IS NULL AND deployment_member_item_id IS NULL
)
""".strip()
REQUIREMENT_SUBJECT_EXPRESSION = f"""(standalone_execution_id IS NULL AND ({DEPLOYMENT_REQUIREMENT_EXPRESSION})) OR (
    standalone_execution_id IS NOT NULL AND TRIM(standalone_execution_id) <> ''
    AND plan_id IS NOT NULL AND item_id IS NULL AND epic_id IS NULL
    AND task_num IS NULL AND deployment_run_id IS NULL
    AND deployment_stage IS NULL AND deployment_member_item_id IS NULL
    AND workflow_transition_id IS NULL
)
""".strip()

STANDALONE_EXECUTION_INDEX_SQL = f"""
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plan_executions_standalone_active
ON qa_plan_executions(standalone_plan_id)
WHERE standalone_plan_id IS NOT NULL
AND state IN ({LIVE_EXECUTION_STATE_SQL});
"""
STANDALONE_REQUIREMENT_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_requirements_standalone_case
ON qa_requirements(standalone_execution_id,plan_id,plan_case_key,COALESCE(host_baseline,''))
WHERE standalone_execution_id IS NOT NULL;
"""
STANDALONE_INDEX_SQL = STANDALONE_EXECUTION_INDEX_SQL + STANDALONE_REQUIREMENT_INDEX_SQL


def supported_subject_expressions(table: str) -> tuple[str, ...]:
    from yoke_core.domain.qa_deployment_scope_schema import (
        LEGACY_EXECUTION_SUBJECT_EXPRESSION,
        LEGACY_REQUIREMENT_SUBJECT_EXPRESSION,
    )

    if table == "qa_plan_executions":
        return (
            LEGACY_EXECUTION_SUBJECT_EXPRESSION,
            DEPLOYMENT_EXECUTION_EXPRESSION,
            EXECUTION_SUBJECT_EXPRESSION,
        )
    return (
        LEGACY_REQUIREMENT_SUBJECT_EXPRESSION,
        DEPLOYMENT_REQUIREMENT_EXPRESSION,
        REQUIREMENT_SUBJECT_EXPRESSION,
    )


def add_standalone_columns(conn: Any) -> None:
    for table, column, definition in (
        ("qa_plan_executions", "standalone_plan_id", "INTEGER"),
        ("qa_requirements", "standalone_execution_id", "TEXT"),
    ):
        if _table_exists(conn, table):
            _add_column_if_not_exists(conn, table, column, definition)


def replace_standalone_subjects(conn: Any) -> None:
    """Ordered history replaces checks; additive boot only adds selectors."""
    from yoke_core.domain.qa_deployment_scope_schema import _subject_constraints

    add_standalone_columns(conn)
    for table, name, expression in (
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
        if not _table_exists(conn, table):
            continue
        for old in _subject_constraints(conn, table):
            conn.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{old}"')
        conn.execute(
            f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({expression})'
        )
    for statement in STANDALONE_INDEX_SQL.split(";"):
        if statement.strip():
            conn.execute(statement)


def assert_standalone_subjects(conn: Any) -> None:
    """Prove exclusive ownership and retain the deployment index guarantees."""
    from yoke_core.domain.qa_deployment_scope_schema import (
        _assert_indexes,
        _EXECUTION_INDEX_SPECS,
        _REQUIREMENT_INDEX_SPECS,
    )

    for table, name, expression in (
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
        row = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid=%s::regclass AND conname=%s",
            (table, name),
        ).fetchone()
        assert row is not None and canonical_boolean_expression(str(row[0])) == (
            canonical_boolean_expression(f"CHECK ({expression})")
        ), f"{name} does not enforce standalone ownership"
    _assert_indexes(conn, "qa_plan_executions", _EXECUTION_INDEX_SPECS)
    _assert_indexes(conn, "qa_requirements", _REQUIREMENT_INDEX_SPECS)
    _assert_indexes(
        conn,
        "qa_plan_executions",
        (
            (
                "idx_qa_plan_executions_standalone_active",
                ("standalone_plan_id",),
                "standalone_plan_id IS NOT NULL",
            ),
        ),
    )
    _assert_indexes(
        conn,
        "qa_requirements",
        (
            (
                "idx_qa_requirements_standalone_case",
                (
                    "standalone_execution_id",
                    "plan_id",
                    "plan_case_key",
                    "COALESCE(host_baseline,'')",
                ),
                "standalone_execution_id IS NOT NULL",
            ),
        ),
    )

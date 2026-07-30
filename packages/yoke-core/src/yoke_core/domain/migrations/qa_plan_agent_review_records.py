"""Add durable batched agent review to ordered QA plan execution."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_review_schema import (
    assert_qa_plan_review_schema,
    ensure_qa_plan_review_schema,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "qa_plan_agent_review_records"
_STATE_CHECK = "qa_plan_executions_state_check_current"
_LIVE_STATES = ("active", "waiting", "awaiting_agent_review")
_ALL_STATES = (*_LIVE_STATES, "completed", "aborted", "error")


def _require_postgres(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError("QA plan agent review migration requires Postgres authority")


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _replace_state_check(conn: Any) -> None:
    rows = conn.execute(
        "SELECT conname,pg_get_constraintdef(oid) "
        "FROM pg_constraint "
        "WHERE conrelid='qa_plan_executions'::regclass AND contype='c'"
    ).fetchall()
    for name, definition in rows:
        if "state" not in str(definition):
            continue
        conn.execute(
            "ALTER TABLE qa_plan_executions DROP CONSTRAINT "
            + _quoted(str(name))
        )
    values = ", ".join(f"'{value}'" for value in _ALL_STATES)
    conn.execute(
        "ALTER TABLE qa_plan_executions "
        f"ADD CONSTRAINT {_STATE_CHECK} CHECK(state IN ({values}))"
    )


def _replace_live_indexes(conn: Any) -> None:
    states = ", ".join(f"'{value}'" for value in _LIVE_STATES)
    conn.execute("DROP INDEX IF EXISTS idx_qa_plan_executions_active")
    conn.execute(
        "CREATE UNIQUE INDEX idx_qa_plan_executions_active "
        "ON qa_plan_executions(item_id,transition_id) "
        "WHERE item_id IS NOT NULL "
        f"AND state IN ({states})"
    )
    conn.execute(
        "DROP INDEX IF EXISTS idx_qa_plan_executions_deployment_active"
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_qa_plan_executions_deployment_active "
        "ON qa_plan_executions(deployment_run_id) "
        "WHERE deployment_run_id IS NOT NULL "
        f"AND state IN ({states})"
    )


def apply(conn: Any) -> None:
    """Expand the live state and create immutable bundle/verdict authority."""
    _require_postgres(conn)
    required = (
        "qa_plan_executions",
        "qa_plan_execution_results",
        "qa_requirements",
        "qa_runs",
        "decision_requests",
    )
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA plan agent review migration requires deployed tables: "
            + ", ".join(missing)
        )
    _replace_state_check(conn)
    _replace_live_indexes(conn)
    ensure_qa_plan_review_schema(conn)


def invariants(conn: Any) -> None:
    """Require review tables and fail-closed uniqueness through review."""
    _require_postgres(conn)
    assert_qa_plan_review_schema(conn)
    checks = [
        str(row[0])
        for row in conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='qa_plan_executions'::regclass AND contype='c'"
        ).fetchall()
    ]
    if not any(
        all(f"'{state}'" in definition for state in _ALL_STATES)
        for definition in checks
    ):
        raise AssertionError(
            "QA plan execution state constraint lacks agent-review state"
        )
    indexes = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT indexname,indexdef FROM pg_indexes "
            "WHERE schemaname=current_schema() "
            "AND tablename='qa_plan_executions'"
        ).fetchall()
    }
    for name in (
        "idx_qa_plan_executions_active",
        "idx_qa_plan_executions_deployment_active",
    ):
        if "awaiting_agent_review" not in indexes.get(name, ""):
            raise AssertionError(f"{name} does not protect pending agent review")


__all__ = ["MIGRATION_NAME", "apply", "invariants"]

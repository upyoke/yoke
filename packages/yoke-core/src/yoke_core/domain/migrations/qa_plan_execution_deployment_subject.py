"""Allow durable QA plan executions to belong to deployment runs."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import (
    _column_exists,
    _get_check_constraint_defs,
    _index_exists,
    _table_exists,
)


MIGRATION_NAME = "qa_plan_execution_deployment_subject"
_SUBJECT_CHECK = "qa_plan_executions_subject_check"


def _require_postgres(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn):
        raise RuntimeError(
            "QA plan execution subject migration requires Postgres authority"
        )


def apply(conn: Any) -> None:
    """Expand the execution authority from item-only to a typed subject."""
    _require_postgres(conn)
    required = ("qa_plan_executions", "deployment_runs")
    missing = [table for table in required if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "QA plan execution subject migration requires deployed tables: "
            + ", ".join(missing)
        )
    if not _column_exists(
        conn,
        "qa_plan_executions",
        "deployment_run_id",
    ):
        conn.execute("ALTER TABLE qa_plan_executions ADD COLUMN deployment_run_id TEXT")
    conn.execute("ALTER TABLE qa_plan_executions ALTER COLUMN item_id DROP NOT NULL")
    conn.execute(
        "ALTER TABLE qa_plan_executions ALTER COLUMN transition_id DROP NOT NULL"
    )
    row = conn.execute(
        "SELECT 1 FROM pg_constraint "
        "WHERE conrelid='qa_plan_executions'::regclass "
        "AND conname=%s",
        (_SUBJECT_CHECK,),
    ).fetchone()
    if row is None:
        conn.execute(
            "ALTER TABLE qa_plan_executions "
            f"ADD CONSTRAINT {_SUBJECT_CHECK} CHECK ("
            "(item_id IS NOT NULL AND deployment_run_id IS NULL "
            "AND transition_id IS NOT NULL) OR "
            "(item_id IS NULL AND deployment_run_id IS NOT NULL "
            "AND transition_id IS NULL))"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "idx_qa_plan_executions_deployment_active "
        "ON qa_plan_executions(deployment_run_id) "
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


def invariants(conn: Any) -> None:
    """Require the dual-subject columns, check, and live-row index."""
    _require_postgres(conn)
    if not _column_exists(
        conn,
        "qa_plan_executions",
        "deployment_run_id",
    ):
        raise AssertionError("qa_plan_executions.deployment_run_id is missing")
    nullability = {
        str(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT column_name,is_nullable FROM information_schema.columns "
            "WHERE table_schema=current_schema() "
            "AND table_name='qa_plan_executions' "
            "AND column_name IN ('item_id','transition_id')"
        ).fetchall()
    }
    if nullability != {"item_id": "YES", "transition_id": "YES"}:
        raise AssertionError(
            "QA plan execution item and transition columns must be nullable"
        )
    checks = _get_check_constraint_defs(conn, "qa_plan_executions")
    if not any(
        "deployment_run_id" in definition
        and "item_id" in definition
        and "transition_id" in definition
        for definition in checks
    ):
        raise AssertionError(
            "QA plan executions lack the item-or-deployment-run subject check"
        )
    if not _index_exists(
        conn,
        "idx_qa_plan_executions_deployment_active",
        "qa_plan_executions",
    ):
        raise AssertionError(
            "deployment-run QA plan execution uniqueness index is missing"
        )
    if not _index_exists(
        conn,
        "idx_qa_requirement_deployment_materialization",
        "qa_requirements",
    ):
        raise AssertionError(
            "deployment-run QA plan materialization uniqueness index is missing"
        )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]

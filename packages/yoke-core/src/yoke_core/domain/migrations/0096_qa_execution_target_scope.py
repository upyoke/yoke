"""Partition stage executions by target without rewriting durable execution rows.

Stop or drain older serving builds before this cutover: their additive boot
can recreate the obsolete index, or fail after multiple target rows exist.
The serving floor enforces that rollout order as it does for scoped QA.
"""

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_deployment_scope_schema import (
    EXECUTION_SCOPE_INDEX_SQL,
    EXECUTION_INDEX_SPECS,
    _assert_indexes,
)
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRES_INVARIANTS = ("0088_shared_qa_execution_per_session",)


def apply(conn: Any) -> None:
    if _table_exists(conn, "qa_plan_executions"):
        for statement in EXECUTION_SCOPE_INDEX_SQL.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute(
            "DROP INDEX IF EXISTS idx_qa_plan_executions_deployment_stage_active"
        )


def invariants(conn: Any) -> None:
    if _table_exists(conn, "qa_plan_executions"):
        _assert_indexes(conn, "qa_plan_executions", EXECUTION_INDEX_SPECS)
        if (
            conn.execute(
                "SELECT to_regclass('idx_qa_plan_executions_deployment_stage_active')"
            ).fetchone()[0]
            is not None
        ):
            raise AssertionError("obsolete stage execution index still exists")

"""Govern durable ordered QA plan execution records."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_execution_schema import (
    assert_qa_plan_execution_schema_invariants,
    converge_qa_plan_execution_schema,
)


MIGRATION_NAME = "qa_plan_execution_records"


def apply(conn: Any) -> None:
    """Create only the declared plan execution tables and indexes."""
    converge_qa_plan_execution_schema(conn)


def invariants(conn: Any) -> None:
    """Require the complete durable plan execution record shape."""
    assert_qa_plan_execution_schema_invariants(conn)


__all__ = ["MIGRATION_NAME", "apply", "invariants"]

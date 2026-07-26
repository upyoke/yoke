"""Read the execution contract for one method-backed QA case."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one


class QaCaseExecutionError(ValueError):
    """A requirement cannot be executed through the shared case runner."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json_object(raw: Any) -> dict:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        value = {}
    if not isinstance(value, dict):
        raise QaCaseExecutionError("case method_config must be a JSON object")
    return value


def get_case_execution_context(
    conn: Any, *, requirement_id: int,
) -> dict[str, Any]:
    """Return the client-local executor contract for a method-backed case."""
    marker = _p(conn)
    row = query_one(
        conn,
        "SELECT q.id AS requirement_id, q.item_id, q.plan_id, "
        "q.plan_case_key, q.method_id, q.qa_kind, q.instructions, "
        "q.expected_outcome, q.method_config, q.host_baseline, "
        "q.workflow_transition_id, c.entry_surface, "
        "c.required_completion, i.worktree, p.id AS project_id, "
        "p.slug AS project, m.name AS method_name, m.executor_id, "
        "m.required_capability_kind, m.verdict_path "
        "FROM qa_requirements q "
        "LEFT JOIN qa_plan_cases c "
        "ON c.plan_id=q.plan_id AND c.case_key=q.plan_case_key "
        "JOIN items i ON i.id=q.item_id "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN qa_methods m ON m.id=q.method_id "
        f"WHERE q.id={marker} AND q.waived_at IS NULL",
        (int(requirement_id),),
    )
    if row is None:
        raise QaCaseExecutionError(
            f"materialized QA case requirement {requirement_id} not found"
        )
    if not row["method_id"]:
        raise QaCaseExecutionError(
            "shared case execution requires a method-backed requirement"
        )
    plan_id = (
        int(row["plan_id"]) if row["plan_id"] is not None else None
    )
    case_key = (
        str(row["plan_case_key"])
        if row["plan_case_key"]
        else f"ad-hoc-{int(row['requirement_id'])}"
    )
    return {
        "requirement_id": int(row["requirement_id"]),
        "item_id": int(row["item_id"]),
        "plan_id": plan_id,
        "case_key": case_key,
        "method_id": str(row["method_id"]),
        "method_name": str(row["method_name"]),
        "executor_id": str(row["executor_id"]),
        "required_capability_kind": row["required_capability_kind"],
        "verdict_path": str(row["verdict_path"]),
        "qa_kind": str(row["qa_kind"]),
        "instructions": str(row["instructions"] or ""),
        "expected_outcome": str(row["expected_outcome"] or ""),
        "method_config": _json_object(row["method_config"]),
        "host_baseline": row["host_baseline"],
        "entry_surface": row["entry_surface"],
        "required_completion": row["required_completion"],
        "workflow_transition_id": row["workflow_transition_id"],
        "project_id": int(row["project_id"]),
        "project": str(row["project"]),
        "worktree": row["worktree"],
    }


__all__ = [
    "QaCaseExecutionError",
    "get_case_execution_context",
]

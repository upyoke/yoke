"""Read the execution contract for one method-backed QA case."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)


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
    conn: Any,
    *,
    requirement_id: int,
) -> dict[str, Any]:
    """Return the client-local executor contract for a method-backed case."""
    marker = _p(conn)
    row = query_one(
        conn,
        "SELECT q.id AS requirement_id, q.item_id, q.deployment_run_id, "
        "q.plan_id, "
        "q.plan_case_key, q.method_id, q.qa_kind, q.instructions, "
        "q.expected_outcome, q.method_config, q.host_baseline, "
        "q.workflow_transition_id, q.entry_surface, "
        "q.required_completion, q.method_name, q.executor_id, "
        "q.required_capability_kind, q.verdict_path, "
        f"{primary_item_worktree_branch_sql('i.id')} AS lane_branch, "
        "p.id AS project_id, "
        "p.slug AS project "
        "FROM qa_requirements q "
        "LEFT JOIN items i ON i.id=q.item_id "
        "LEFT JOIN deployment_runs dr ON dr.id=q.deployment_run_id "
        "JOIN projects p ON p.id=COALESCE(i.project_id, dr.project_id) "
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
    plan_id = int(row["plan_id"]) if row["plan_id"] is not None else None
    method_snapshot = {
        "method_name": row["method_name"],
        "executor_id": row["executor_id"],
        "required_capability_kind": row["required_capability_kind"],
        "verdict_path": row["verdict_path"],
    }
    if not all(
        str(method_snapshot[key] or "").strip()
        for key in ("method_name", "executor_id", "verdict_path")
    ):
        if plan_id is not None:
            raise QaCaseExecutionError(
                "materialized QA case execution snapshot is incomplete; "
                "apply the QA requirement snapshot migration"
            )
        method = query_one(
            conn,
            "SELECT name AS method_name, executor_id, "
            "required_capability_kind, verdict_path FROM qa_methods "
            f"WHERE id={marker}",
            (str(row["method_id"]),),
        )
        if method is None:
            raise QaCaseExecutionError(
                f"ad-hoc QA method {row['method_id']!r} is not registered"
            )
        method_snapshot = dict(method)
    case_key = (
        str(row["plan_case_key"])
        if row["plan_case_key"]
        else f"ad-hoc-{int(row['requirement_id'])}"
    )
    return {
        "requirement_id": int(row["requirement_id"]),
        "item_id": (int(row["item_id"]) if row["item_id"] is not None else None),
        "deployment_run_id": row["deployment_run_id"],
        "plan_id": plan_id,
        "case_key": case_key,
        "method_id": str(row["method_id"]),
        "method_name": str(method_snapshot["method_name"]),
        "executor_id": str(method_snapshot["executor_id"]),
        "required_capability_kind": method_snapshot["required_capability_kind"],
        "verdict_path": str(method_snapshot["verdict_path"]),
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
        "lane_branch": row["lane_branch"],
    }


__all__ = [
    "QaCaseExecutionError",
    "get_case_execution_context",
]

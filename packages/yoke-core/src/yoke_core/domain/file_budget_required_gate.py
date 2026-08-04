"""Required File Budget gate resolved from an item's pinned workflow."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.file_budget_paths import has_resolved_file_budget
from yoke_core.domain.path_claim_spec_coverage_gate import _read_spec_text
from yoke_core.domain.path_claim_task_coverage import (
    eligible_task_status_clause,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_effective_policies import (
    load_item_effective_workflow_policies,
)

GATE_PASS = "pass"
GATE_BLOCK = "block"
_POLICY_READ_SAVEPOINT = "file_budget_policy_read"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _load_effective_policy(conn: Any, item_id: int):
    conn.execute(f"SAVEPOINT {_POLICY_READ_SAVEPOINT}")
    try:
        effective = load_item_effective_workflow_policies(conn, int(item_id))
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {_POLICY_READ_SAVEPOINT}")
        conn.execute(f"RELEASE SAVEPOINT {_POLICY_READ_SAVEPOINT}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {_POLICY_READ_SAVEPOINT}")
    return effective


def workflow_policy_schema_available(conn: Any) -> bool:
    """Whether policy-aware gates can read a complete immutable item pin."""
    required = {
        "items": ("workflow_id", "workflow_version_id", "workflow_posture"),
        "workflow_versions": (
            "id", "workflow_id", "version", "definition_json",
            "definition_digest",
        ),
    }
    return all(
        _table_exists(conn, table)
        and all(_column_exists(conn, table, column) for column in columns)
        for table, columns in required.items()
    )


def _required_task_budgets(
    conn: Any,
    item_id: int,
    *,
    require_finalized: bool = True,
) -> dict[str, object]:
    item_ref = render_item_ref(conn, int(item_id))
    if not all(
        _table_exists(conn, table)
        for table in ("epic_tasks", "epic_task_files")
    ):
        return {
            "verdict": GATE_BLOCK,
            "reason": "task-scoped File Budget schema is incomplete",
            "missing_tasks": [],
        }
    from yoke_core.domain.epic_task_scope import (
        schema_available as task_scope_schema_available,
        task_scope_issues,
    )

    marker = _p(conn)
    rows = conn.execute(
        "SELECT t.task_num, COUNT(CASE WHEN "
        "TRIM(COALESCE(f.file_path, '')) <> '' THEN 1 END) AS file_count "
        "FROM epic_tasks t LEFT JOIN epic_task_files f "
        "ON f.epic_id = t.epic_id AND f.task_num = t.task_num "
        f"WHERE t.epic_id = {marker} "
        f"AND {eligible_task_status_clause('t.status')} "
        "GROUP BY t.task_num ORDER BY t.task_num",
        (int(item_id),),
    ).fetchall()
    if not rows:
        return {
            "verdict": GATE_PASS,
            "reason": (
                f"item {item_ref} defers task File Budgets until "
                "planning persists generated tasks"
            ),
            "missing_tasks": [],
        }
    if task_scope_schema_available(conn):
        issues = task_scope_issues(
            conn,
            int(item_id),
            require_finalized=require_finalized,
        )
        if issues:
            missing = [
                int(row["task_num"] if hasattr(row, "keys") else row[0])
                for row in rows
                if int(row["file_count"] if hasattr(row, "keys") else row[1]) == 0
            ]
            return {
                "verdict": GATE_BLOCK,
                "reason": (
                    f"item {item_ref} generated task scope is incomplete: "
                    + "; ".join(issues)
                ),
                "missing_tasks": missing,
            }
        return {
            "verdict": GATE_PASS,
            "reason": (
                f"item {item_ref} has finalized explicit scope for every "
                "generated task"
            ),
            "missing_tasks": [],
        }
    missing = [
        int(row["task_num"] if hasattr(row, "keys") else row[0])
        for row in rows
        if int(row["file_count"] if hasattr(row, "keys") else row[1]) == 0
    ]
    if missing:
        return {
            "verdict": GATE_BLOCK,
            "reason": (
                f"item {item_ref} generated task(s) lack a persisted "
                "File Budget: " + ", ".join(map(str, missing))
            ),
            "missing_tasks": missing,
        }
    return {
        "verdict": GATE_PASS,
        "reason": (
            f"item {item_ref} has a persisted File Budget for every "
            "generated task"
        ),
        "missing_tasks": [],
    }


def evaluate_required_budget(
    conn: Any,
    item_id: int,
    *,
    task_scoped: bool = False,
    require_finalized: bool = True,
) -> dict[str, object]:
    """Evaluate target-shaped required coverage without reading the pin."""
    item_ref = render_item_ref(conn, int(item_id))
    if task_scoped:
        return _required_task_budgets(
            conn,
            int(item_id),
            require_finalized=require_finalized,
        )
    spec = _read_spec_text(conn, int(item_id))
    if has_resolved_file_budget(spec):
        return {
            "verdict": GATE_PASS,
            "reason": f"item {item_ref} declares a resolved File Budget",
            "missing_tasks": [],
        }
    return {
        "verdict": GATE_BLOCK,
        "reason": (
            f"item {item_ref} has no resolved ## File Budget section"
        ),
        "missing_tasks": [],
    }


def evaluate(conn: Any, item_id: int) -> dict[str, object]:
    """Evaluate the effective File Budget requirement for one item."""
    item_ref = render_item_ref(conn, int(item_id))
    if not workflow_policy_schema_available(conn):
        return {
            "verdict": GATE_PASS,
            "reason": "workflow pin schema unavailable; legacy gate applies",
            "missing_tasks": [],
        }
    try:
        effective = _load_effective_policy(conn, int(item_id))
    except Exception as exc:
        return {
            "verdict": GATE_BLOCK,
            "reason": (
                f"item {item_ref} has an unreadable pinned File Budget "
                f"policy: {exc}"
            ),
            "missing_tasks": [],
        }
    if not effective.requires_file_budget:
        return {
            "verdict": GATE_PASS,
            "reason": (
                f"item {item_ref} effective workflow policy makes "
                "File Budget optional"
            ),
            "missing_tasks": [],
        }
    return evaluate_required_budget(
        conn,
        item_id,
        task_scoped=effective.file_budget == "required_per_task",
    )


__all__ = [
    "GATE_BLOCK",
    "GATE_PASS",
    "evaluate",
    "evaluate_required_budget",
    "workflow_policy_schema_available",
]

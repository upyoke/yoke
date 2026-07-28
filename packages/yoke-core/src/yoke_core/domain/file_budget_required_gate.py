"""Required File Budget gate resolved from an item's pinned workflow."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.file_budget_paths import has_resolved_file_budget
from yoke_core.domain.path_claim_spec_coverage_gate import _read_spec_text
from yoke_core.domain.path_claim_task_coverage import (
    eligible_task_status_clause,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_effective_policies import (
    load_item_effective_workflow_policies,
)

GATE_PASS = "pass"
GATE_BLOCK = "block"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _required_task_budgets(conn: Any, item_id: int) -> dict[str, object]:
    if not all(
        _table_exists(conn, table)
        for table in ("epic_tasks", "epic_task_files")
    ):
        return {
            "verdict": GATE_BLOCK,
            "reason": "task-scoped File Budget schema is incomplete",
            "missing_tasks": [],
        }
    marker = _p(conn)
    rows = conn.execute(
        "SELECT t.task_num, COUNT(f.file_path) AS file_count "
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
                f"item YOK-{item_id} defers task File Budgets until "
                "planning persists generated tasks"
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
                f"item YOK-{item_id} generated task(s) lack a persisted "
                "File Budget: " + ", ".join(map(str, missing))
            ),
            "missing_tasks": missing,
        }
    return {
        "verdict": GATE_PASS,
        "reason": (
            f"item YOK-{item_id} has a persisted File Budget for every "
            "generated task"
        ),
        "missing_tasks": [],
    }


def evaluate(conn: Any, item_id: int) -> dict[str, object]:
    """Evaluate the effective File Budget requirement for one item."""
    try:
        effective = load_item_effective_workflow_policies(conn, int(item_id))
    except Exception as exc:
        return {
            "verdict": GATE_BLOCK,
            "reason": (
                f"item YOK-{item_id} has an unreadable pinned File Budget "
                f"policy: {exc}"
            ),
            "missing_tasks": [],
        }
    if not effective.requires_file_budget:
        return {
            "verdict": GATE_PASS,
            "reason": (
                f"item YOK-{item_id} effective workflow policy makes "
                "File Budget optional"
            ),
            "missing_tasks": [],
        }
    if effective.file_budget == "required_per_task":
        return _required_task_budgets(conn, int(item_id))
    spec = _read_spec_text(conn, int(item_id))
    if has_resolved_file_budget(spec):
        return {
            "verdict": GATE_PASS,
            "reason": f"item YOK-{item_id} declares a resolved File Budget",
            "missing_tasks": [],
        }
    return {
        "verdict": GATE_BLOCK,
        "reason": (
            f"item YOK-{item_id} has no resolved ## File Budget section"
        ),
        "missing_tasks": [],
    }


__all__ = ["GATE_BLOCK", "GATE_PASS", "evaluate"]

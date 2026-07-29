"""Fail-closed eligibility for deferring dormant task-scoped plans."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


_PRE_EXECUTION_TASK_STAGES = ("planned", "plan-drafted")


def safe_to_defer_empty_legacy_plan(
    conn: Any,
    item_id: int,
    item_status: str,
    tasks: list[dict[str, Any]],
) -> bool:
    """Keep dormant legacy plans blocked until task budgets are authored."""
    if item_status not in _PRE_EXECUTION_TASK_STAGES or not tasks or any(
        task["task_status"] not in _PRE_EXECUTION_TASK_STAGES for task in tasks
    ):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    active_claim = conn.execute(
        "SELECT 1 FROM path_claims "
        f"WHERE item_id = {marker} AND state = 'active' LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if active_claim is not None:
        return False
    if not _table_exists(conn, "work_claims"):
        return True
    live_work = conn.execute(
        "SELECT 1 FROM work_claims "
        f"WHERE (item_id = {marker} OR epic_id = {marker}) "
        "AND released_at IS NULL LIMIT 1",
        (int(item_id), int(item_id)),
    ).fetchone()
    return live_work is None


__all__ = ["safe_to_defer_empty_legacy_plan"]

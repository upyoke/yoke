"""Select actionable plan snapshots while counting retained history."""

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_store import marker


def plan_drift_rows(conn: Any, plan_id: int) -> tuple[list[dict], int]:
    """Finished subjects remain stored without entering the correction queue."""
    rows = query_rows(
        conn,
        "SELECT q.*, (COALESCE(i.status IN ('done','cancelled'), FALSE) OR "
        "COALESCE(e.state IN ('completed','aborted','error'), FALSE)) AS historical "
        "FROM qa_requirements q LEFT JOIN items i ON i.id=COALESCE(q.item_id,q.epic_id) "
        "LEFT JOIN qa_plan_executions e ON e.id=q.standalone_execution_id "
        f"WHERE q.plan_id={marker(conn)} AND q.waived_at IS NULL ORDER BY q.id",
        (int(plan_id),),
    )
    return (
        [row for row in rows if not row["historical"]],
        sum(bool(row["historical"]) for row in rows),
    )

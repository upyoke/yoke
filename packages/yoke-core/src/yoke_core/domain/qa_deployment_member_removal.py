"""Settle a removed release member's QA cursors and their host ownership."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def abort_removed_member_executions(conn: Any, *, run_id: str, item_id: int) -> None:
    """Abort only this run/member's live executions in the caller's transaction.

    Clear every queue intent before releasing any reservation: releasing one
    host must never grant it to another cursor of the same removed member.
    Existing terminal evidence and other members' executions survive.
    """
    if not _table_exists(conn, "qa_plan_executions"):
        return
    rows = query_rows(
        conn,
        "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
        f"AND deployment_member_item_id=%s AND state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        "ORDER BY id",
        (run_id, item_id),
    )
    executions = [lock_plan_execution(conn, str(row["id"])) for row in rows]
    executions = [
        e for e in executions if e["state"] not in TERMINAL_PLAN_EXECUTION_STATES
    ]
    for execution in executions:
        conn.execute(
            "UPDATE qa_plan_executions SET release_reason=NULL WHERE id=%s",
            (execution["id"],),
        )
    for execution in executions:
        finish_plan_execution(
            conn,
            execution,
            state="aborted",
            reason="deployment-member-removed",
            commit=False,
        )

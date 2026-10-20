"""Retire an unsuccessful deployment's QA on its closing transaction."""

from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_latest_execution import latest_execution_id_sql
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_plan_attachment_retract import retract_requirements
from yoke_core.domain.qa_plan_execution_abort_state import abort_request
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
from yoke_core.domain.schema_common import _table_exists


def settle_unsuccessful_run(conn: Any, run_id: str, *, reason: str) -> None:
    """Abort live cursors and retract unfulfilled run obligations without committing.

    A cursor already settling through a recorded abort is left to that abort.
    """
    executions = [
        lock_plan_execution(conn, str(row["id"]))
        for row in (
            query_rows(
                conn,
                "SELECT id FROM qa_plan_executions WHERE deployment_run_id=%s "
                f"AND state IN ({LIVE_PLAN_EXECUTION_SQL}) ORDER BY id",
                (run_id,),
            )
            if _table_exists(conn, "qa_plan_executions")
            else []
        )
    ]
    # An execution already under a cooperative abort keeps its held host
    # until its own cleanup proof settles it (a removed member's walk, say).
    executions = [
        e
        for e in executions
        if e["state"] not in TERMINAL_PLAN_EXECUTION_STATES and abort_request(e) is None
    ]
    # Clear queue intents together before a released host can grant the next
    # cursor from this same closed run.
    for execution in executions:
        conn.execute(
            "UPDATE qa_plan_executions SET release_reason=NULL WHERE id=%s",
            (execution["id"],),
        )
    for execution in executions:
        finish_plan_execution(
            conn, execution, state="aborted", reason=reason, commit=False
        )
    if not _table_exists(conn, "qa_requirements"):
        return
    rows = query_rows(
        conn,
        "SELECT r.id FROM qa_requirements r WHERE r.deployment_run_id=%s "
        f"AND NOT {settled_obligation_sql(conn, 'r')} "
        "AND NOT EXISTS (SELECT 1 FROM qa_runs qr "
        f"WHERE qr.id=({latest_execution_id_sql('r.id')}) AND qr.verdict='pass')",
        (run_id,),
    )
    retract_requirements(
        conn, [int(row["id"]) for row in rows], reason=reason, source="deployment_run"
    )


def restore_retry_obligations(conn: Any, run_id: str) -> None:
    """Reinstate only this run's automatic retirements on an authorized retry.

    A member removed since the failure owes the retry nothing, so only shared
    rows and current members' rows come back.
    """
    if _table_exists(conn, "qa_requirements"):
        conn.execute(
            "UPDATE qa_requirements SET retracted_at=NULL, "
            "retraction_rationale=NULL, retraction_source=NULL "
            "WHERE deployment_run_id=%s AND retraction_source='deployment_run' "
            "AND (deployment_member_item_id IS NULL OR deployment_member_item_id IN "
            "(SELECT item_id FROM deployment_run_items WHERE run_id=%s))",
            (run_id, run_id),
        )

"""A released, unconsumed host turn ends the waiting execution it was held for.

``reserve_host_turn`` reserves a free host for the oldest waiter. When that
reservation's lease is released before the waiter takes it, the wait is
cancelled. A ``waiting`` plan execution left with no live wait on any host
can never be served again, yet it still counts as an open walk, so control-
plane upkeep would never wake its owner. It is therefore aborted in the same
transaction with :data:`HOST_TURN_RELEASED_REASON`, naming the fresh run that
recovers it; an aborted execution cannot be resumed.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_plan_execution_store import marker as _p

#: Abort code of a waiting execution whose reserved host turn was released.
HOST_TURN_RELEASED_REASON = "qa_host_turn_released"
_LIVE = "('waiting','reserved')"


def cancel_released_reservation(conn: Any, claim: Any) -> None:
    """Cancel *claim*'s unconsumed reservation; abort an execution it orphans."""
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT id,qa_plan_execution_id FROM qa_test_machine_waits "
        f"WHERE claim_id={p} AND state='reserved'",
        (claim.id,),
    )
    if not rows:
        return
    conn.execute(
        f"UPDATE qa_test_machine_waits SET state='cancelled',settled_at={p} "
        f"WHERE claim_id={p} AND state='reserved'",
        (instant_parameter(conn, utc_now()), claim.id),
    )
    executions = {str(r["qa_plan_execution_id"]) for r in rows if r["qa_plan_execution_id"]}
    for execution_id in sorted(executions):
        _abort_orphaned(conn, execution_id, test_machine=str(claim.target.test_machine))


def _abort_orphaned(conn: Any, execution_id: str, *, test_machine: str) -> None:
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution

    p = _p(conn)
    if query_one(
        conn,
        "SELECT id FROM qa_test_machine_waits "
        f"WHERE qa_plan_execution_id={p} AND state IN {_LIVE}",
        (execution_id,),
    ):
        return
    execution = lock_plan_execution(conn, execution_id)
    if execution["state"] != "waiting":
        return
    finish_plan_execution(
        conn,
        execution,
        state="aborted",
        reason=(
            f"{HOST_TURN_RELEASED_REASON}: the reserved turn on QA host "
            f"{test_machine} was released before this execution took it; "
            f"start a fresh run with `{rerun_command(conn, execution)}`"
        ),
        commit=False,
    )


def rerun_command(conn: Any, execution: Mapping[str, Any]) -> str:
    """The fresh ``yoke qa plan run`` for the subject *execution* walked."""
    from yoke_core.domain.project_identity import render_item_ref

    stage = execution.get("deployment_stage")
    if stage:
        from yoke_core.domain.deployment_qa_failure_handoff import (
            retry_command_for_stage,
        )

        member = execution.get("deployment_member_item_id")
        return retry_command_for_stage(
            conn,
            run_id=str(execution["deployment_run_id"]),
            stage=str(stage),
            member_ref=None,
            member_id=int(member) if member is not None else None,
            project=None,
        )
    plan_id = execution.get("standalone_plan_id")
    if plan_id is not None:
        row = query_one(
            conn,
            "SELECT p.slug FROM qa_plans q JOIN projects p ON p.id=q.project_id "
            f"WHERE q.id={_p(conn)}",
            (int(plan_id),),
        )
        project = f" --project {row['slug']}" if row is not None else ""
        return f"yoke qa plan run --plan {plan_id}{project}"
    item_id, transition = execution.get("item_id"), execution.get("transition_id")
    if item_id is not None and transition:
        return (
            f"yoke qa plan run --item {render_item_ref(conn, int(item_id))} "
            f"--transition {transition}"
        )
    return "yoke qa plan run with this execution's subject flags (see --help)"

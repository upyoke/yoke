"""Transfer an ended session's QA cursor to its item's current work holder."""

from __future__ import annotations

from uuid import uuid4

from yoke_core.domain.db_helpers import instant_parameter, query_one, utc_now
from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_subject
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    lock_plan_execution,
    same_owner,
)
from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit


def adopt_execution(
    conn,
    execution_id,
    *,
    item_id=None,
    deployment_run_id=None,
    actor_id,
    session_id,
    reason,
):
    """Change only ownership, with an atomic durable transfer receipt.

    Host custody, frozen targets, captures and terminal state retain their
    existing owners and validators. Adoption alone never revives a host lease
    released by termination or turns an aborted walk into an active one.
    """
    execution = lock_plan_execution(conn, execution_id)
    require_plan_execution_subject(
        execution, item_id=item_id, deployment_run_id=deployment_run_id
    )
    owner_item = (
        execution.get("item_id")
        or execution.get("deployment_member_item_id")
        or execution.get("requesting_member_item_id")
    )
    if owner_item is None:
        raise QaPlanExecutionStateError(
            "qa_adoption_item_required: this execution has no owning item; "
            "ask its project operator to reconcile standalone or shared QA ownership"
        )
    claim = get_claim_for_work_unit(conn, item_id=str(owner_item))
    if claim is None or str(claim["session_id"]) != session_id:
        raise QaPlanExecutionStateError(
            "qa_adoption_claim_required: acquire the execution item's work claim, then retry adoption"
        )
    # Serialize release/termination with the transfer, rechecking after locking.
    held = query_one(
        conn, "SELECT * FROM work_claims WHERE id=%s FOR UPDATE", (claim["id"],)
    )
    if (
        held is None
        or held["released_at"] is not None
        or str(held["session_id"]) != session_id
    ):
        raise QaPlanExecutionStateError(
            "qa_adoption_claim_lost: reacquire the execution item's work claim, then retry"
        )
    successor = query_one(
        conn,
        "SELECT actor_id,ended_at,terminated_at FROM harness_sessions WHERE session_id=%s",
        (session_id,),
    )
    if (
        successor is None
        or successor["ended_at"]
        or successor["terminated_at"]
        or str(successor["actor_id"]) != str(actor_id)
    ):
        raise QaPlanExecutionStateError(
            "qa_adoption_successor_invalid: use a live registered session holding the item claim"
        )
    if same_owner(execution, actor_id=actor_id, session_id=session_id):
        conn.commit()
        return {
            "execution_id": execution_id,
            "state": "already_owned",
            "session_id": session_id,
        }
    previous = query_one(
        conn,
        "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id=%s",
        (execution["session_id"],),
    )
    if previous is None:
        raise QaPlanExecutionStateError(
            "qa_adoption_owner_unverified: predecessor session evidence is missing; ask steering to reconcile it before adoption"
        )
    if not (previous["ended_at"] or previous["terminated_at"]):
        raise QaPlanExecutionStateError(
            "qa_adoption_owner_live: the predecessor has not ended; have it finish or ask steering to terminate it before restaffing"
        )
    adoption_id = str(uuid4())
    now = instant_parameter(conn, utc_now())
    conn.execute(
        "INSERT INTO qa_plan_execution_adoptions "
        "(id,execution_id,item_id,work_claim_id,previous_actor_id,previous_session_id,actor_id,session_id,reason,adopted_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            adoption_id,
            execution_id,
            owner_item,
            claim["id"],
            execution.get("actor_id"),
            execution["session_id"],
            str(actor_id),
            session_id,
            reason,
            now,
        ),
    )
    conn.execute(
        "UPDATE qa_plan_executions SET actor_id=%s,session_id=%s WHERE id=%s",
        (str(actor_id), session_id, execution_id),
    )
    conn.commit()
    return {
        "execution_id": execution_id,
        "state": "adopted",
        "adoption_id": adoption_id,
        "previous_session_id": str(execution["session_id"]),
        "session_id": session_id,
    }

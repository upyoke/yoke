"""Record that an item has no post-deploy obligation, and why.

An item that is not observable from outside once deployed owes no check
after its deploy. That fact is not a waiver: a waiver says an obligation
existed and we chose not to satisfy it. Recording emptiness under
``waived_at`` destroys the signal in the one listing an auditor uses for
real exceptions.

This write is one act against the item's own ``post_deploy`` requirement
row. The row is non-blocking, carries ``qa_kind``
``post_deploy_no_obligation``, stores the reason on ``instructions``, and
leaves every waiver column empty. The shared classifier in
:mod:`yoke_core.domain.post_deploy_verification_answer` is the only reader
of that fact.

The row binds to the item's pinned release wait, the first stage
:mod:`yoke_core.domain.qa_phase_boundary` lets a post-deploy row bind to.
Repeating the command returns the fact already recorded rather than a
second row.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)
from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_requirement_insert import (
    INSERT_SQL,
    RequirementSubject,
    insert_params,
)
from yoke_core.domain.post_deploy_verification_answer import (
    NO_OBLIGATION_QA_KIND,
    answer_for_item,
)
from yoke_core.domain.qa_deployment_member_attached_plans import (
    DEPLOYMENT_ATTACHMENT_PHASE,
)
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


class QaPostDeployRecordNoObligationRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class QaPostDeployRecordNoObligationResponse(BaseModel):
    requirement_id: int
    item_id: int
    workflow_transition_id: str
    reason: str
    already_recorded: bool


def _release_wait(conn: Any, item_id: int) -> tuple[str, str]:
    """The stage a post-deploy fact binds to, or why there is none."""
    workflow = load_item_workflow_runtime(conn, int(item_id))
    stage = delivery_redirect_stage(workflow)
    if not stage:
        return "", (
            f"{workflow.workflow_id}@{workflow.version} declares no release "
            "wait, so it never reaches a deployment and has no post-deploy "
            "obligation to record. Nothing to record."
        )
    return str(stage), ""


def _existing_fact(conn: Any, item_id: int) -> Optional[dict]:
    """This item's recorded no-obligation fact, so a repeat is not a second row."""
    from yoke_core.domain.db_helpers import query_one

    return query_one(
        conn,
        "SELECT id,instructions,workflow_transition_id FROM qa_requirements "
        "WHERE item_id=%s AND qa_phase=%s AND qa_kind=%s "
        "AND deployment_run_id IS NULL AND waived_at IS NULL "
        "ORDER BY id LIMIT 1",
        (int(item_id), DEPLOYMENT_ATTACHMENT_PHASE, NO_OBLIGATION_QA_KIND),
    )


def handle_qa_post_deploy_record_no_obligation(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Write the item's recorded no-post-deploy-obligation fact."""
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.post_deploy.record_no_obligation requires target.item_id",
        )
    try:
        body = QaPostDeployRecordNoObligationRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _error(
            "payload_invalid",
            f"record-no-obligation payload invalid: {exc}",
        )

    conn = connect()
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        transition_id, refusal = _release_wait(conn, int(item_id))
        if refusal:
            return _error("payload_invalid", refusal)
        recorded = _existing_fact(conn, int(item_id))
        if recorded is not None:
            return HandlerOutcome(
                result_payload={
                    "requirement_id": int(recorded["id"]),
                    "item_id": int(item_id),
                    "workflow_transition_id": str(
                        recorded["workflow_transition_id"] or transition_id
                    ),
                    "reason": str(recorded["instructions"] or ""),
                    "already_recorded": True,
                },
                primary_success=True,
            )
        if not answer_for_item(conn, int(item_id)).unanswered:
            return _error(
                "payload_invalid",
                "this item already has post-deploy verification to do, so it "
                "cannot record that it has none. An attached plan or a live "
                "case is the answer; retire what it owes rather than "
                "declaring the obligation away.",
            )
        row = {
            "qa_kind": NO_OBLIGATION_QA_KIND,
            "qa_phase": DEPLOYMENT_ATTACHMENT_PHASE,
            "blocking_mode": "non_blocking",
            "instructions": body.reason,
            "workflow_transition_id": transition_id,
        }
        cur = conn.execute(
            INSERT_SQL.format(p=_p(conn)),
            insert_params(
                RequirementSubject.for_item(int(item_id)), row, iso8601_now()
            ),
        )
        requirement_id = int(cur.fetchone()[0])
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementCreated",
            requirement_id=requirement_id,
            qa_kind=NO_OBLIGATION_QA_KIND,
            qa_phase=DEPLOYMENT_ATTACHMENT_PHASE,
            target_row={
                "item_id": int(item_id),
                "epic_id": None,
                "task_num": None,
                "deployment_run_id": None,
            },
        )
        conn.commit()
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": requirement_id,
            "item_id": int(item_id),
            "workflow_transition_id": transition_id,
            "reason": body.reason,
            "already_recorded": False,
        },
        primary_success=True,
    )


__all__ = [
    "QaPostDeployRecordNoObligationRequest",
    "QaPostDeployRecordNoObligationResponse",
    "handle_qa_post_deploy_record_no_obligation",
]

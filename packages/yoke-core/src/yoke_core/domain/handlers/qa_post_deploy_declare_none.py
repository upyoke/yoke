"""Record that an item needs no post-deploy verification, and why.

An item that genuinely has nothing to check after its deploy is a real
category, and the answer for it cannot be "attach a plan anyway". The
storage for that answer already existed: a ``post_deploy`` requirement
waived with its reason carries ``waived_at``, ``waiver_rationale`` and
``waiver_source``, emits ``QARequirementWaived``, and already clears the
done gate's post-deploy blocker.

What did not exist was a way to record it as one act. Composing it out of
``qa requirement add`` plus ``qa requirement waive`` makes the owner
manufacture the obligation they are declining, which teaches the opposite
of what this surface is for. So the declaration is written here in one
call, against those same tables and that same event.

The row binds to the item's pinned release wait, the first stage
:mod:`yoke_core.domain.qa_phase_boundary` lets a post-deploy row bind to,
and it is non-blocking: a declaration is the answer to the question, never
a fresh obligation waiting on one.
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
    DECLARATION_QA_KIND,
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


class QaPostDeployDeclareNoneRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    source: str = "agent"


class QaPostDeployDeclareNoneResponse(BaseModel):
    requirement_id: int
    item_id: int
    workflow_transition_id: str
    reason: str
    already_declared: bool


def _release_wait(conn: Any, item_id: int) -> tuple[str, str]:
    """The stage a post-deploy declaration binds to, or why there is none."""
    workflow = load_item_workflow_runtime(conn, int(item_id))
    stage = delivery_redirect_stage(workflow)
    if not stage:
        return "", (
            f"{workflow.workflow_id}@{workflow.version} declares no release "
            "wait, so it never reaches a deployment and has no post-deploy "
            "verification to decline. Nothing to declare."
        )
    return str(stage), ""


def _existing_declaration(conn: Any, item_id: int) -> Optional[dict]:
    """This item's recorded declaration, so a repeat is not a second row."""
    from yoke_core.domain.db_helpers import query_one

    return query_one(
        conn,
        "SELECT id,waiver_rationale,workflow_transition_id FROM qa_requirements "
        "WHERE item_id=%s AND qa_phase=%s AND qa_kind=%s "
        "AND deployment_run_id IS NULL ORDER BY id LIMIT 1",
        (int(item_id), DEPLOYMENT_ATTACHMENT_PHASE, DECLARATION_QA_KIND),
    )


def handle_qa_post_deploy_declare_none(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Write the item's recorded nothing-to-verify declaration."""
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_events import emit_qa_requirement_event
    from yoke_core.domain.qa_requirement_ops import waive_requirement

    item_id = request.target.item_id
    if item_id is None:
        return _error(
            "target_invalid",
            "qa.post_deploy.declare_none requires target.item_id",
        )
    try:
        body = QaPostDeployDeclareNoneRequest.model_validate(
            request.payload or {}
        )
    except Exception as exc:
        return _error("payload_invalid", f"declare-none payload invalid: {exc}")
    if body.source not in {"agent", "operator"}:
        return _error(
            "payload_invalid",
            "source must be one of ['agent', 'operator']",
            jsonpath="$.payload.source",
        )

    conn = connect()
    try:
        lock_item_workflow_bindings(conn, (int(item_id),))
        transition_id, refusal = _release_wait(conn, int(item_id))
        if refusal:
            return _error("payload_invalid", refusal)
        recorded = _existing_declaration(conn, int(item_id))
        if recorded is not None:
            # A repeated call is the same answer, not a second one.
            return HandlerOutcome(
                result_payload={
                    "requirement_id": int(recorded["id"]),
                    "item_id": int(item_id),
                    "workflow_transition_id": str(
                        recorded["workflow_transition_id"] or transition_id
                    ),
                    "reason": str(recorded["waiver_rationale"] or ""),
                    "already_declared": True,
                },
                primary_success=True,
            )
        if not answer_for_item(conn, int(item_id)).unanswered:
            return _error(
                "payload_invalid",
                "this item already has post-deploy verification to do, so it "
                "cannot declare that it has none. Retire what it owes first: "
                "`yoke qa requirement waive --requirement-id N --rationale "
                "TEXT` records the same decision per case, and a plan it no "
                "longer needs is detached rather than declared away.",
            )
        row = {
            "qa_kind": DECLARATION_QA_KIND,
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
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=None,
            event_name="QARequirementCreated",
            requirement_id=requirement_id,
            qa_kind=DECLARATION_QA_KIND,
            qa_phase=DEPLOYMENT_ATTACHMENT_PHASE,
            target_row={
                "item_id": int(item_id),
                "epic_id": None,
                "task_num": None,
                "deployment_run_id": None,
            },
        )
        # The waiver is what makes the row a settled declaration rather than
        # a fresh obligation, and it is where the reason becomes durable and
        # attributable. Non-blocking, so it needs no force override.
        waive_requirement(conn, requirement_id, body.reason, source=body.source)
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "requirement_id": requirement_id,
            "item_id": int(item_id),
            "workflow_transition_id": transition_id,
            "reason": body.reason,
            "already_declared": False,
        },
        primary_success=True,
    )


__all__ = [
    "QaPostDeployDeclareNoneRequest",
    "QaPostDeployDeclareNoneResponse",
    "handle_qa_post_deploy_declare_none",
]

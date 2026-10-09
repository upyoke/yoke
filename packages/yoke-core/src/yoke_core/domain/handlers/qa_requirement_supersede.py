"""QA requirement supersession handler."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from yoke_core.domain.handlers.qa import _error
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)


class QaRequirementSupersedeRequest(BaseModel):
    superseded_by_requirement_id: int = Field(..., gt=0)
    rationale: str = Field(..., min_length=1)
    source: str = "agent"
    declare_replacement: bool = False
    reconcile: bool = False


class QaRequirementSupersedeResponse(BaseModel):
    requirement_id: int
    superseded_by_requirement_id: Optional[int] = None
    superseded_at: Optional[str] = None
    supersession_rationale: Optional[str] = None
    supersession_source: Optional[str] = None
    replacement_requirement_id: Optional[int] = None
    deployment_run_id: Optional[str] = None
    deployment_stage: Optional[str] = None
    deployment_member_item_id: Optional[int] = None
    item_id: Optional[int] = None
    workflow_transition_id: Optional[str] = None
    correction_notice: Optional[dict[str, str]] = None
    #: Present only when the discharged row was an admitted copy whose intake
    #: requirement is still outstanding, because supersession is run-local and
    #: the next release admits that row again untouched.
    admitted_from_requirement_id: Optional[int] = None
    next_admission_notice: Optional[str] = None
    #: Present only when the superseded row was a post_deploy item source
    #: retired in favor of a corrected item requirement: the passing run case
    #: that proved the corrected body and answers for its own run.
    run_replacement_requirement_id: Optional[int] = None


def handle_qa_requirement_supersede(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    target = request.target
    req_id: Optional[int] = target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.requirement.supersede requires target.qa_requirement_id",
        )
    try:
        body = QaRequirementSupersedeRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"supersede payload invalid: {exc}")

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_supersession import (
        QaSupersessionError,
        supersede_requirement,
    )
    from yoke_core.domain.qa_requirement_replacement import (
        QaReplacementError,
        declare_existing_replacement,
    )

    from yoke_core.domain.qa_requirement_successor import (
        QaSuccessorError,
        authorize_reconciliation,
    )

    conn = connect()
    try:
        try:
            if body.reconcile:
                if body.declare_replacement or body.source != "operator":
                    return _error(
                        "payload_invalid",
                        "Reconciliation requires --source operator and cannot declare a pending replacement",
                    )
                authorize_reconciliation(conn, request, int(req_id))
                body.rationale = f"actor={request.actor.actor_id} session={request.actor.session_id}: {body.rationale}"
            if body.declare_replacement:
                declared = declare_existing_replacement(
                    conn,
                    failed_id=int(req_id),
                    replacement_id=int(body.superseded_by_requirement_id),
                )
                conn.commit()
                if not declared.get("deployment_run_id"):
                    # An item case has no run holder to wake; the gate that
                    # grades it re-reads the declaration on its next pass.
                    return HandlerOutcome(result_payload=declared, primary_success=True)
                from yoke_core.domain.deployment_qa_correction_notice import (
                    notify_correction,
                )

                try:
                    notice = notify_correction(
                        conn, result=declared, replacements=[declared]
                    )
                except Exception as exc:  # declaration already committed
                    conn.rollback()
                    from yoke_core.domain.project_identity import render_item_ref

                    member = declared.get("deployment_member_item_id")
                    scope = (
                        f" --member {render_item_ref(conn, int(member))}"
                        if member is not None
                        else ""
                    )
                    notice = {
                        "delivery": "failed",
                        "recovery": f"Correction is durable but wake failed: {exc}. Run "
                        f"`yoke watch qa-plan -- --deployment-run-id "
                        f"{declared['deployment_run_id']} --stage "
                        f"{declared['deployment_stage']}{scope}`.",
                    }
                return HandlerOutcome(
                    result_payload={**declared, "correction_notice": notice},
                    primary_success=True,
                )
            result = supersede_requirement(
                conn,
                requirement_id=int(req_id),
                superseded_by_requirement_id=int(body.superseded_by_requirement_id),
                rationale=body.rationale,
                source=body.source,
                reconcile=body.reconcile,
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except (QaSupersessionError, QaSuccessorError) as exc:
            return _error("supersession_refused", str(exc))
        except QaReplacementError as exc:
            return _error("replacement_refused", str(exc))
    finally:
        conn.close()

    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "QaRequirementSupersedeRequest",
    "QaRequirementSupersedeResponse",
    "handle_qa_requirement_supersede",
]

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
    correction_notice: Optional[dict[str, str]] = None
    #: Present only when the discharged row was an admitted copy whose intake
    #: requirement is still outstanding, because supersession is run-local and
    #: the next release admits that row again untouched.
    admitted_from_requirement_id: Optional[int] = None
    next_admission_notice: Optional[str] = None


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

    conn = connect()
    try:
        try:
            if body.declare_replacement:
                declared = declare_existing_replacement(
                    conn, failed_id=int(req_id),
                    replacement_id=int(body.superseded_by_requirement_id),
                )
                conn.commit()
                from yoke_core.domain.deployment_qa_correction_notice import notify_correction

                try:
                    notice = notify_correction(
                        conn, result=declared, replacements=[declared]
                    )
                except Exception as exc:  # declaration already committed
                    conn.rollback()
                    notice = {"delivery": "failed", "recovery":
                              f"Correction is durable but wake failed: {exc}. Run "
                              f"`yoke watch qa-plan -- --deployment-run-id "
                              f"{declared['deployment_run_id']} --stage "
                              f"{declared['deployment_stage']} --member "
                              f"{declared['deployment_member_item_id']}`."}
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
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except QaSupersessionError as exc:
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

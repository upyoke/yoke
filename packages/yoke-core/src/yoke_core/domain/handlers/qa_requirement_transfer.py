"""Registered direct QA case ownership transfer."""

from pydantic import BaseModel, Field
from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa import _error


class QaRequirementTransferRequest(BaseModel):
    destination: str = Field(min_length=1)
    workflow_transition_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class QaRequirementTransferResponse(BaseModel):
    requirement_id: int
    from_item_id: int
    to_item_id: int
    workflow_transition_id: str
    rationale: str
    session_id: str
    transferred_at: str


def handle_qa_requirement_transfer(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_requirement_transfer import transfer_requirement

    if request.target.qa_requirement_id is None:
        return _error("target_invalid", "Name target.qa_requirement_id to transfer")
    body = QaRequirementTransferRequest.model_validate(request.payload or {})
    conn = connect()
    try:
        try:
            result = transfer_requirement(
                conn,
                requirement_id=request.target.qa_requirement_id,
                destination=body.destination,
                transition=body.workflow_transition_id,
                rationale=body.rationale,
                session_id=str(request.actor.session_id or ""),
                request_id=str(request.request_id),
            )
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return _error("requirement_transfer_refused", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)

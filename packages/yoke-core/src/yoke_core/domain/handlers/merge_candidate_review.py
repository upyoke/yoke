"""Function handler for the merge boundary's candidate-review gate."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)

FUNCTION_ID = "merge_review.candidate.evaluate"


class CandidateReviewEvaluateRequest(BaseModel):
    commit_sha: str
    branch: str = ""
    target: str = ""
    touched_files: List[str] = Field(default_factory=list)


class CandidateReviewEvaluateResponse(BaseModel):
    required: bool
    satisfied: bool
    item_id: int
    commit_sha: str
    reason: str
    request_id: Optional[int] = None
    request_status: str = ""
    resolution_action: Optional[str] = None
    superseded_request_ids: List[int] = Field(default_factory=list)


def _error(code: str, message: str, *, jsonpath: Optional[str] = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_candidate_evaluate(request: FunctionCallRequest) -> HandlerOutcome:
    """Answer whether this exact candidate head may land, raising the ask."""
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return _error(
            "target_invalid",
            f"{FUNCTION_ID} requires a resolved item target",
            jsonpath="$.target.item_id",
        )
    try:
        body = CandidateReviewEvaluateRequest.model_validate(request.payload or {})
    except Exception as exc:  # Pydantic renders the exact invalid field
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.merge_candidate_review_gate import (
        evaluate_candidate_review,
    )

    actor_id: Optional[int] = None
    raw_actor = (request.actor.actor_id or "").strip()
    if raw_actor.isdigit():
        actor_id = int(raw_actor)
    conn = db_helpers.connect()
    try:
        verdict = evaluate_candidate_review(
            conn,
            item_id=int(target.item_id),
            commit_sha=body.commit_sha,
            branch=body.branch,
            target=body.target,
            touched_files=body.touched_files,
            originator_actor_id=actor_id,
            session_id=str(request.actor.session_id or ""),
        )
    except LookupError as exc:
        conn.rollback()
        return _error("item_not_found", str(exc), jsonpath="$.target.item_id")
    except ValueError as exc:
        conn.rollback()
        return _error("payload_invalid", str(exc), jsonpath="$.payload.commit_sha")
    finally:
        conn.close()
    result: dict[str, Any] = verdict.as_dict()
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "CandidateReviewEvaluateRequest",
    "CandidateReviewEvaluateResponse",
    "FUNCTION_ID",
    "handle_candidate_evaluate",
]

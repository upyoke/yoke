"""Registered convergence for decision requests whose subjects have ended."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.inbox_decision_models import (
    DecisionDisposeEndedRequest,
    DecisionDisposeEndedResponse,
)


def handle_decision_dispose_ended(request: FunctionCallRequest) -> HandlerOutcome:
    """Reap non-progressing QA walks and withdraw every ended-subject ask."""
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="decision_requests.dispose_ended requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    try:
        model = DecisionDisposeEndedRequest.model_validate(request.payload or {})
    except Exception as exc:  # Pydantic renders the exact invalid field
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid", message=str(exc), jsonpath="$.payload"
            ),
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_request_disposition import (
        dispose_ended_decision_requests,
    )

    conn = db_helpers.connect()
    try:
        result = dispose_ended_decision_requests(
            conn,
            project_ids=model.project_ids,
            session_id=request.actor.session_id,
        )
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "DecisionDisposeEndedRequest",
    "DecisionDisposeEndedResponse",
    "handle_decision_dispose_ended",
]

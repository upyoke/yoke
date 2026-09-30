"""Actor-scoped read of one decision request and its durable decisions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError, HandlerOutcome


class DecisionRequestGetRequest(BaseModel):
    request_id: int


class DecisionRequestGetResponse(BaseModel):
    request: dict[str, Any]


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(primary_success=False, error=FunctionError(code=code, message=message))


def handle_decision_request_get(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error("target_invalid", "decision_requests.get requires a global target")
    raw_actor = str(request.actor.actor_id or "")
    if not raw_actor.isdecimal():
        return _error("actor_required", "decision_requests.get requires a bound actor; run from an authenticated session")
    try:
        payload = DecisionRequestGetRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc))

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.decision_request_rows import request_row
    from yoke_core.domain.decision_request_authority import authority_reason
    from yoke_core.domain.decision_answers import decision_by_actor

    with connect() as conn:
        try:
            row = request_row(conn, payload.request_id)
        except LookupError:
            return _error("not_found", f"decision request {payload.request_id} not found")
        actor_id = int(raw_actor)
        reason = authority_reason(conn, payload.request_id, actor_id, request=row)
        prior = decision_by_actor(row["decisions"], actor_id)
        if reason is None and prior is None and row.get("originator_actor_id") != actor_id:
            return _error("not_found", f"decision request {payload.request_id} not found for this actor")
        row["authority_reason"] = reason
        row["your_decision"] = prior
    return HandlerOutcome(primary_success=True, result_payload={"request": row})


__all__ = ["DecisionRequestGetRequest", "DecisionRequestGetResponse", "handle_decision_request_get"]

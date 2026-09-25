"""Governed browser action for the stale-session cleanup sweep."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class SessionsReclaimStaleRequest(BaseModel):
    confirm: bool = False
    project_ids: Optional[List[int]] = None


class SessionsReclaimStaleResponse(BaseModel):
    never_engaged: List[Dict[str, Any]]
    heartbeat_stale: List[Dict[str, Any]]
    progress_stale: List[Dict[str, Any]]
    skipped_between_turns: List[Dict[str, Any]]
    total_reclaimed: int
    scratch_cleanup: Dict[str, Any]


def handle_sessions_reclaim_stale(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="sessions.reclaim_stale requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    try:
        payload = SessionsReclaimStaleRequest.model_validate(
            request.payload or {},
        )
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    if not payload.confirm:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="confirmation_required",
                message=(
                    "confirm=true is required; the sweep rechecks liveness "
                    "before releasing any stale claim"
                ),
                jsonpath="$.payload.confirm",
            ),
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions

    conn = connect()
    try:
        result = clean_stale_harness_sessions(
            conn,
            project_ids=payload.project_ids,
        )
    finally:
        conn.close()
    return HandlerOutcome(result_payload=result, primary_success=True)


__all__ = [
    "SessionsReclaimStaleRequest",
    "SessionsReclaimStaleResponse",
    "handle_sessions_reclaim_stale",
]

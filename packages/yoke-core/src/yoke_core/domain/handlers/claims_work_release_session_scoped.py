"""Yoke function handler for ``claims.work.release_session_scoped``.

Thin shim around
:func:`yoke_core.domain.claims_work_release_session_scoped.release_all_claims_for_session`.
The handler resolves the calling session id from the request envelope and
releases every active ``work_claims`` row that session still owns. No
target body is required — the target IS the calling session.

Why ``claim_required_kind=None``: the dispatcher's claim-verification
matrix gates by item / epic / self-only-claim authority. This primitive
only ever releases the caller's own claims (strict same-session
``WHERE session_id = ?`` filter); the security boundary falls out of
that SQL, not a target-claim check.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ReleaseSessionScopedRequest(BaseModel):
    """Empty payload — target is the calling session, resolved server-side."""

    model_config = ConfigDict(extra="forbid")


class ReleaseSessionScopedResponse(BaseModel):
    released_count: int = Field(..., ge=0)
    released_claims: List[Dict[str, Any]] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_release_session_scoped(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Release every active work-claim the calling session still owns."""
    session_id = request.actor.session_id
    if not session_id:
        return _err("payload_invalid", "actor.session_id is required")

    # Validate payload shape so unexpected fields surface early.
    try:
        ReleaseSessionScopedRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _err(
            "payload_invalid",
            f"release_session_scoped payload invalid: {exc}",
        )

    from yoke_core.domain.claims_work_release_session_scoped import (
        release_all_claims_for_session,
    )

    result = release_all_claims_for_session(session_id)
    return HandlerOutcome(result_payload=result)


__all__ = [
    "ReleaseSessionScopedRequest",
    "ReleaseSessionScopedResponse",
    "handle_release_session_scoped",
]

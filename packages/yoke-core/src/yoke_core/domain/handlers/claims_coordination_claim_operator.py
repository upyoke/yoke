"""Hosted human recovery for stranded coordination claims."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend


class HumanOperatorRequired(ValueError):
    """The request did not come from an authenticated session-less human."""


class OperatorReleaseRequest(BaseModel):
    project_id: str
    key: str
    claim_id: int
    holder_session_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class OperatorReleaseResponse(BaseModel):
    released: bool
    claim_id: int
    project_id: int
    key: str
    prior_session_id: str
    operator_actor_id: int
    operator_reason: str
    released_at: str


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_operator_release(request: FunctionCallRequest) -> HandlerOutcome:
    """Release the exact claim an authorized human reviewed."""
    try:
        body = OperatorReleaseRequest.model_validate(request.payload)
    except Exception as exc:
        return _error("payload_invalid", f"operator release payload invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.coordination_claims import (
        CoordinationClaimError,
        CoordinationClaimHookContextError,
        CoordinationClaimNotFoundError,
    )
    from yoke_core.domain.coordination_claims_operator import (
        CoordinationClaimChangedError,
        operator_release,
    )

    try:
        with db_helpers.connect() as conn:
            actor_id = _authenticated_human_actor(conn, request)
            result: dict[str, Any] = operator_release(
                conn,
                project_id=body.project_id,
                key=body.key,
                operator_reason=body.reason,
                expected_claim_id=body.claim_id,
                expected_holder_session_id=body.holder_session_id,
                operator_actor_id=actor_id,
            )
    except CoordinationClaimChangedError as exc:
        return _error("claim_changed", str(exc))
    except CoordinationClaimHookContextError as exc:
        return _error("hook_context", str(exc))
    except CoordinationClaimNotFoundError as exc:
        return _error("claim_not_found", str(exc))
    except CoordinationClaimError as exc:
        return _error("claim_error", str(exc))
    except HumanOperatorRequired as exc:
        return _error("human_operator_required", str(exc))
    except (LookupError, ValueError) as exc:
        return _error("payload_invalid", str(exc))

    return HandlerOutcome(result_payload=result)


def _authenticated_human_actor(conn: Any, request: FunctionCallRequest) -> int:
    """Resolve a signed-in human action and refuse every harness session."""
    if request.actor.session_id:
        raise HumanOperatorRequired(
            "Run this recovery as a signed-in human "
            "action outside a harness session; manual and launched agent "
            "sessions cannot authorize it"
        )
    raw_actor = str(request.actor.actor_id or "").strip()
    if not raw_actor.isdigit():
        raise HumanOperatorRequired(
            "Sign in as a project owner before running stranded-claim recovery"
        )
    actor_id = int(raw_actor)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT kind FROM actors WHERE id = {marker}", (actor_id,)
    ).fetchone()
    if row is None or str(row[0]) != "human":
        raise HumanOperatorRequired("The authenticated actor is not a human")
    return actor_id


__all__ = [
    "OperatorReleaseRequest",
    "OperatorReleaseResponse",
    "HumanOperatorRequired",
    "handle_operator_release",
]

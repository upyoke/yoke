"""Path-claim read handlers: claims.path.list, claims.path.get.

Wrap the projections in :mod:`yoke_core.domain.path_claims_read` — the
same rich shapes the ``db_router path-claims list|get`` operator-debug
CLI prints. Both ids carry ``claim_required_kind=None`` (reads).
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_VALID_CLAIM_STATES = frozenset(
    {"planned", "blocked", "active", "released", "cancelled"}
)


class ClaimsPathListRequest(BaseModel):
    states: List[str] = Field(
        default_factory=list,
        description=(
            "Optional state filter (planned/blocked/active/released/"
            "cancelled). Empty -> all states."
        ),
    )


class ClaimsPathListResponse(BaseModel):
    item_id: int
    claims: List[Dict[str, Any]]


class ClaimsPathGetRequest(BaseModel):
    pass


class ClaimsPathGetResponse(BaseModel):
    claim: Dict[str, Any]


def handle_claims_path_list(request: FunctionCallRequest) -> HandlerOutcome:
    target = request.target
    if target.kind != "item" or target.item_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="claims.path.list requires target.kind='item' with item_id",
            ),
        )
    states = [str(s) for s in (request.payload or {}).get("states") or []]
    unknown = sorted(set(states) - _VALID_CLAIM_STATES)
    if unknown:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=(
                    f"unknown path-claim state(s): {', '.join(unknown)}. "
                    f"Valid: {', '.join(sorted(_VALID_CLAIM_STATES))}"
                ),
                jsonpath="$.payload.states",
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims_read import item_view

    item_id = int(target.item_id)
    conn = connect()
    try:
        claims = item_view(conn, item_id, states=states or None)
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"item_id": item_id, "claims": claims},
        primary_success=True,
    )


def handle_claims_path_get(request: FunctionCallRequest) -> HandlerOutcome:
    claim_id = request.target.path_claim_id
    if request.target.kind != "path_claim" or claim_id is None:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message=(
                    "claims.path.get requires target.kind='path_claim' "
                    "with path_claim_id"
                ),
            ),
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims import PathClaimError
    from yoke_core.domain.path_claims_read import claim_projection

    conn = connect()
    try:
        try:
            projection = claim_projection(conn, int(claim_id))
        except PathClaimError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="not_found",
                    message=str(exc),
                    jsonpath="$.target.path_claim_id",
                ),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"claim": projection},
        primary_success=True,
    )


__all__ = [
    "ClaimsPathListRequest", "ClaimsPathListResponse",
    "handle_claims_path_list",
    "ClaimsPathGetRequest", "ClaimsPathGetResponse",
    "handle_claims_path_get",
]

"""Yoke function handlers for the ``claims.coordination_claim.*`` family.

Operations:

- ``claims.coordination_claim.acquire`` — take a (project, key) claim.
- ``claims.coordination_claim.heartbeat`` — refresh the claim heartbeat.
- ``claims.coordination_claim.release`` — release a held claim by id.
- ``claims.coordination_claim.list`` — list claims (optional filters).

Reuse: thin wrappers over :mod:`yoke_core.domain.coordination_claims`
(and its listing sibling). No claim state-machine logic is
re-implemented here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.coordination_claim_keys import (
    CoordinationKeyError,
    target_for_key,
)
from yoke_core.domain.coordination_claim_record import claim_as_dict


class AcquireRequest(BaseModel):
    project_id: str
    key: str
    item_id: Optional[int] = None
    reason: Optional[str] = None


class ClaimRow(BaseModel):
    id: int
    key: str
    target_kind: str
    scope: Dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[int] = None
    session_id: str
    actor_id: Optional[str] = None
    owner_item_id: Optional[int] = None
    sticky: bool = False
    claimed_at: str
    last_heartbeat: Optional[str] = None
    released_at: Optional[str] = None
    release_reason: Optional[str] = None
    release_reason_intent: Optional[str] = None


class AcquireResponse(BaseModel):
    claim: ClaimRow


class HeartbeatRequest(BaseModel):
    claim_id: int


class HeartbeatResponse(BaseModel):
    claim: ClaimRow


class ReleaseRequest(BaseModel):
    """Address the claim by id, or by the (project, key) it holds.

    A holder that acquired minutes or hours earlier has the key it typed,
    not the row id the acquire returned, so releasing its own hold must
    not require a lookup step first.
    """

    claim_id: Optional[int] = None
    project_id: Optional[str] = None
    key: Optional[str] = None
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    claim: ClaimRow


class ListRequest(BaseModel):
    project_id: Optional[str] = None
    key: Optional[str] = None
    session_id: Optional[str] = None
    owner_item_id: Optional[int] = None
    active_only: bool = False


class ListResponse(BaseModel):
    claims: List[ClaimRow] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _reserved(key: str) -> bool:
    """Qualification grants open only through the session-control surface."""
    from yoke_core.domain.coordination_claim_keys import kind_for_key
    from yoke_core.domain.work_claim_targets import TARGET_KIND_ROUTE_QUALIFICATION

    return kind_for_key(key) == TARGET_KIND_ROUTE_QUALIFICATION


def handle_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = AcquireRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"acquire payload invalid: {exc}")
    if _reserved(body.key):
        return _err(
            "claim_key_reserved",
            "reserved qualification claims open only through session-control",
        )

    from yoke_core.domain.coordination_claims import (
        CoordinationClaimHeldError,
        CoordinationClaimStaleHolderError,
        acquire,
    )
    from yoke_core.domain.project_identity import resolve_project

    with _connect_rw() as conn:
        try:
            identity = resolve_project(conn, body.project_id)
            assert identity is not None
            target = target_for_key(
                body.key,
                project_id=identity.id,
                item_id=body.item_id,
                project_slug=identity.slug,
            )
        except LookupError as exc:
            return _err("project_not_found", str(exc))
        except CoordinationKeyError as exc:
            return _err("claim_key_unknown", str(exc))
        except ValueError as exc:
            return _err("payload_invalid", str(exc))
        try:
            claim = acquire(
                conn, target, request.actor.session_id, reason=body.reason
            )
        except CoordinationClaimStaleHolderError as exc:
            return _err("claim_stale_holder", str(exc))
        except CoordinationClaimHeldError as exc:
            return _err("claim_held", str(exc))

    return HandlerOutcome(result_payload={"claim": claim_as_dict(claim)})


def handle_heartbeat(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = HeartbeatRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"heartbeat payload invalid: {exc}")

    from yoke_core.domain.coordination_claims import (
        CoordinationClaimNotFoundError,
        CoordinationClaimReleasedError,
        get_claim,
        heartbeat,
    )

    with _connect_rw() as conn:
        try:
            if _reserved(get_claim(conn, int(body.claim_id)).key):
                return _err(
                    "claim_key_reserved",
                    "reserved qualification claims cannot be heartbeated "
                    "generically",
                )
            claim = heartbeat(conn, int(body.claim_id))
        except CoordinationClaimNotFoundError as exc:
            return _err("claim_not_found", str(exc))
        except CoordinationClaimReleasedError as exc:
            return _err("claim_released", str(exc))

    return HandlerOutcome(result_payload={"claim": claim_as_dict(claim)})


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReleaseRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"release payload invalid: {exc}")

    from yoke_core.domain.coordination_claims import (
        CoordinationClaimNotFoundError,
        get_claim,
        release,
    )

    with _connect_rw() as conn:
        try:
            claim_id = _release_target_id(conn, body)
        except LookupError as exc:
            return _err("claim_not_found", str(exc))
        except CoordinationKeyError as exc:
            return _err("claim_key_unknown", str(exc))
        except ValueError as exc:
            return _err("payload_invalid", str(exc))
        try:
            if _reserved(get_claim(conn, claim_id).key):
                return _err(
                    "claim_key_reserved",
                    "reserved qualification claims cannot be released "
                    "generically",
                )
            claim = release(conn, claim_id, body.reason)
        except CoordinationClaimNotFoundError as exc:
            return _err("claim_not_found", str(exc))

    return HandlerOutcome(result_payload={"claim": claim_as_dict(claim)})


def _release_target_id(conn: Any, body: "ReleaseRequest") -> int:
    """Resolve the claim row this release names, by id or by key."""
    if body.claim_id is not None:
        return int(body.claim_id)
    if not body.key or not body.project_id:
        raise ValueError(
            "release requires claim_id, or project_id together with key"
        )
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.project_identity import resolve_project

    identity = resolve_project(conn, body.project_id)
    assert identity is not None
    target = target_for_key(
        body.key, project_id=identity.id, project_slug=identity.slug
    )
    claim = active_claim(conn, target)
    if claim is None:
        raise LookupError(
            f"no active coordination claim for {identity.slug}:{body.key}"
        )
    return int(claim.id)


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ListRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"list payload invalid: {exc}")

    from yoke_core.domain.coordination_claims_listing import list_claims

    with _connect_rw() as conn:
        claims = list_claims(
            conn,
            project_id=body.project_id,
            key=body.key,
            session_id=body.session_id,
            owner_item_id=body.owner_item_id,
            active_only=body.active_only,
        )

    return HandlerOutcome(
        result_payload={"claims": [claim_as_dict(claim) for claim in claims]},
    )


__all__ = [
    "AcquireRequest",
    "AcquireResponse",
    "ClaimRow",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "ListRequest",
    "ListResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "handle_acquire",
    "handle_heartbeat",
    "handle_list",
    "handle_release",
]

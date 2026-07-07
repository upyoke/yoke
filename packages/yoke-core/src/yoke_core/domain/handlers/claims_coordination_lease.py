"""Yoke function handlers for the ``claims.coordination_lease.*`` family.

Operations:

- ``claims.coordination_lease.acquire`` — acquire a (project, key) lease.
- ``claims.coordination_lease.heartbeat`` — refresh ``heartbeat_at``.
- ``claims.coordination_lease.release`` — release a held lease by id.
- ``claims.coordination_lease.list`` — list leases (optional filters).

Reuse: thin wrappers over
:mod:`yoke_core.domain.coordination_leases` (and its listing sibling).
No lease state-machine logic is re-implemented here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class AcquireRequest(BaseModel):
    project_id: str
    lease_key: str
    actor_id: Optional[str] = None


class LeaseRow(BaseModel):
    id: int
    project_id: str
    lease_key: str
    session_id: str
    actor_id: Optional[str] = None
    acquired_at: str
    heartbeat_at: Optional[str] = None
    released_at: Optional[str] = None
    release_reason: Optional[str] = None


class AcquireResponse(BaseModel):
    lease: LeaseRow


class HeartbeatRequest(BaseModel):
    lease_id: int


class HeartbeatResponse(BaseModel):
    lease: LeaseRow


class ReleaseRequest(BaseModel):
    lease_id: int
    reason: str = Field(..., min_length=1)


class ReleaseResponse(BaseModel):
    lease: LeaseRow


class ListRequest(BaseModel):
    project_id: Optional[str] = None
    lease_key: Optional[str] = None
    session_id: Optional[str] = None
    active_only: bool = False


class ListResponse(BaseModel):
    leases: List[LeaseRow] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _lease_to_dict(lease: Any) -> Dict[str, Any]:
    return {
        "id": int(lease.id),
        "project_id": str(lease.project_id),
        "lease_key": str(lease.lease_key),
        "session_id": str(lease.session_id),
        "actor_id": lease.actor_id,
        "acquired_at": lease.acquired_at,
        "heartbeat_at": lease.heartbeat_at,
        "released_at": lease.released_at,
        "release_reason": lease.release_reason,
    }


def handle_acquire(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = AcquireRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"acquire payload invalid: {exc}")

    from yoke_core.domain.coordination_leases import (
        LeaseHeldError,
        acquire_lease,
    )

    with _connect_rw() as conn:
        try:
            lease = acquire_lease(
                conn, body.project_id, body.lease_key,
                request.actor.session_id, actor_id=body.actor_id,
            )
        except LeaseHeldError as exc:
            return _err("lease_held", str(exc))

    return HandlerOutcome(result_payload={"lease": _lease_to_dict(lease)})


def handle_heartbeat(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = HeartbeatRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"heartbeat payload invalid: {exc}")

    from yoke_core.domain.coordination_leases import (
        LeaseNotFoundError,
        LeaseReleasedError,
        heartbeat_lease,
    )

    with _connect_rw() as conn:
        try:
            lease = heartbeat_lease(conn, int(body.lease_id))
        except LeaseNotFoundError as exc:
            return _err("lease_not_found", str(exc))
        except LeaseReleasedError as exc:
            return _err("lease_released", str(exc))

    return HandlerOutcome(result_payload={"lease": _lease_to_dict(lease)})


def handle_release(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ReleaseRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"release payload invalid: {exc}")

    from yoke_core.domain.coordination_leases import (
        LeaseNotFoundError,
        release_lease,
    )

    with _connect_rw() as conn:
        try:
            lease = release_lease(conn, int(body.lease_id), body.reason)
        except LeaseNotFoundError as exc:
            return _err("lease_not_found", str(exc))

    return HandlerOutcome(result_payload={"lease": _lease_to_dict(lease)})


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        body = ListRequest.model_validate(request.payload)
    except Exception as exc:
        return _err("payload_invalid", f"list payload invalid: {exc}")

    from yoke_core.domain.coordination_leases import list_leases

    with _connect_rw() as conn:
        leases = list_leases(
            conn,
            project_id=body.project_id,
            lease_key=body.lease_key,
            session_id=body.session_id,
            active_only=body.active_only,
        )

    return HandlerOutcome(
        result_payload={"leases": [_lease_to_dict(l) for l in leases]},
    )


__all__ = [
    "AcquireRequest",
    "AcquireResponse",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "ReleaseRequest",
    "ReleaseResponse",
    "ListRequest",
    "ListResponse",
    "LeaseRow",
    "handle_acquire",
    "handle_heartbeat",
    "handle_release",
    "handle_list",
]

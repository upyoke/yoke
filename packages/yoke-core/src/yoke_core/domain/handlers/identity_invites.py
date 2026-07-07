"""``identity.invite.*`` handlers — org-admission invite lifecycle.

Org-admin-gated at dispatch (``identity.`` prefix -> ORG scope +
``org.admin`` in ``function_authz_scope``). Payload orgs default to the
universe's identity-card org.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    HandlerOutcome,
)

from yoke_core.domain.handlers.identity_common import (
    caller_actor_id,
    payload_error,
    resolve_actor_ref,
    resolve_org_ref,
)


class InviteCreateRequest(BaseModel):
    email: str
    role: Optional[str] = None
    actor: Optional[str] = None
    org: Optional[str] = None


class InviteCreateResponse(BaseModel):
    invite_id: int
    email: str
    org_id: int
    role_id: Optional[int] = None
    actor_id: Optional[int] = None
    status: str


class InviteListRequest(BaseModel):
    status: Optional[str] = None
    org: Optional[str] = None


class InviteListResponse(BaseModel):
    invites: List[Dict[str, Any]]


class InviteRevokeRequest(BaseModel):
    invite_id: int


class InviteRevokeResponse(BaseModel):
    invite_id: int
    status: str


def _parse(model, request: FunctionCallRequest):
    try:
        return model(**(request.payload or {})), None
    except Exception as exc:
        return None, HandlerOutcome(
            primary_success=False, error=payload_error(str(exc)),
        )


def handle_identity_invite_create(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.actor_invites import InviteError, create_invite
    from yoke_core.domain.actor_permissions import ORG_ROLES, role_id_by_name
    from yoke_core.domain.db_helpers import connect

    parsed, failure = _parse(InviteCreateRequest, request)
    if failure is not None:
        return failure
    conn = connect()
    try:
        org_id, org_error = resolve_org_ref(conn, parsed.org)
        if org_error is not None:
            return HandlerOutcome(primary_success=False, error=org_error)
        role_id: Optional[int] = None
        if parsed.role:
            role_name = str(parsed.role).strip()
            if role_name not in ORG_ROLES:
                return HandlerOutcome(
                    primary_success=False,
                    error=payload_error(
                        f"invite role must be an org role {ORG_ROLES}, "
                        f"got {role_name!r}",
                        "$.payload.role",
                    ),
                )
            role_id = role_id_by_name(conn, role_name)
        target_actor_id: Optional[int] = None
        if parsed.actor:
            target_actor_id, actor_error = resolve_actor_ref(
                conn, parsed.actor, "$.payload.actor",
            )
            if actor_error is not None:
                return HandlerOutcome(primary_success=False, error=actor_error)
        try:
            invite = create_invite(
                conn,
                email=parsed.email,
                org_id=org_id,
                invited_by_actor_id=caller_actor_id(conn, request),
                role_id=role_id,
                actor_id=target_actor_id,
            )
        except InviteError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=payload_error(str(exc), "$.payload.email"),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "invite_id": invite.invite_id,
            "email": invite.email,
            "org_id": invite.org_id,
            "role_id": invite.role_id,
            "actor_id": invite.actor_id,
            "status": invite.status,
        },
        primary_success=True,
    )


def handle_identity_invite_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.actor_invites import InviteError, list_invites
    from yoke_core.domain.db_helpers import connect

    parsed, failure = _parse(InviteListRequest, request)
    if failure is not None:
        return failure
    conn = connect()
    try:
        org_id, org_error = resolve_org_ref(conn, parsed.org)
        if org_error is not None:
            return HandlerOutcome(primary_success=False, error=org_error)
        try:
            invites = list_invites(
                conn, org_id=org_id, status=parsed.status or None,
            )
        except InviteError as exc:
            return HandlerOutcome(
                primary_success=False,
                error=payload_error(str(exc), "$.payload.status"),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"invites": [asdict(invite) for invite in invites]},
        primary_success=True,
    )


def handle_identity_invite_revoke(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.actor_invites import (
        InviteNotFound,
        InviteNotPending,
        revoke_invite,
    )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.identity_common import not_found_error

    parsed, failure = _parse(InviteRevokeRequest, request)
    if failure is not None:
        return failure
    conn = connect()
    try:
        try:
            invite = revoke_invite(
                conn,
                invite_id=parsed.invite_id,
                revoked_by_actor_id=caller_actor_id(conn, request),
            )
        except InviteNotFound as exc:
            return HandlerOutcome(
                primary_success=False,
                error=not_found_error(str(exc), "$.payload.invite_id"),
            )
        except InviteNotPending as exc:
            return HandlerOutcome(
                primary_success=False,
                error=payload_error(str(exc), "$.payload.invite_id"),
            )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"invite_id": invite.invite_id, "status": invite.status},
        primary_success=True,
    )


__all__ = [
    "InviteCreateRequest",
    "InviteCreateResponse",
    "InviteListRequest",
    "InviteListResponse",
    "InviteRevokeRequest",
    "InviteRevokeResponse",
    "handle_identity_invite_create",
    "handle_identity_invite_list",
    "handle_identity_invite_revoke",
]

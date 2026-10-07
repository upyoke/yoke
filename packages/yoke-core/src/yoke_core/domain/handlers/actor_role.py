"""Org-admin operation that sets a person's one org role."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
from yoke_core.domain.actor_role import (
    ActorRoleRefused,
    resolve_member_actor,
    set_actor_org_role,
)
from yoke_core.domain.control_plane_authority import require_control_plane_permission


class ActorRoleSetRequest(BaseModel):
    actor_id: Optional[int] = None
    member_email: Optional[str] = None
    role: str


class ActorRoleSetResponse(BaseModel):
    actor_id: int
    role: str
    previous_roles: List[str]
    changed: bool


def _refuse(code: str, message: str, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_actor_role_set(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _refuse("target_invalid", "actors.role.set requires a global target")
    raw_caller = (request.actor.actor_id or "").strip()
    if not raw_caller.isdigit():
        return _refuse("actor_required", "bind an org-admin actor and retry")
    payload = request.payload or {}
    actor_id = payload.get("actor_id")
    member_email = payload.get("member_email")
    role = payload.get("role")
    if (actor_id is None) == (member_email is None):
        return _refuse(
            "payload_invalid", "pass exactly one of actor_id or member_email"
        )
    if actor_id is not None and (
        isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0
    ):
        return _refuse(
            "payload_invalid", "actor_id must be a positive integer", "$.actor_id"
        )
    if member_email is not None and (
        not isinstance(member_email, str) or "@" not in member_email
    ):
        return _refuse(
            "payload_invalid", "member_email must be an email address", "$.member_email"
        )
    if not isinstance(role, str) or not role.strip():
        return _refuse("payload_invalid", "role must be a role name", "$.role")
    with db_helpers.connect() as conn:
        try:
            require_control_plane_permission(
                conn, actor_id=int(raw_caller), permission_key=PERM_ORG_ADMIN
            )
        except PermissionDenied as exc:
            return _refuse("permission_denied", str(exc))
        try:
            if member_email is not None:
                actor_id = resolve_member_actor(conn, member_email)
            change = set_actor_org_role(
                conn,
                actor_id=actor_id,
                role=role.strip(),
                caller_actor_id=int(raw_caller),
                now=db_helpers.iso8601_now(),
            )
        except ActorRoleRefused as exc:
            return _refuse(exc.code, str(exc))
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "actor_id": change.actor_id,
            "role": change.role,
            "previous_roles": change.previous_roles,
            "changed": change.changed,
        },
    )

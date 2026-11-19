"""Org-admin operations that set or remove a person's one org role."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.timestamps import utc_now

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
from yoke_core.domain.actor_role import (
    ActorRoleRefused,
    remove_actor_org_role,
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


class ActorRoleRemoveRequest(BaseModel):
    actor_id: Optional[int] = None
    member_email: Optional[str] = None


class ActorRoleRemoveResponse(BaseModel):
    actor_id: int
    previous_roles: List[str]
    changed: bool


def refuse(code: str, message: str, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def text_field(payload: Dict[str, Any], key: str, what: str) -> HandlerOutcome | str:
    """A required non-empty string field, stripped, or its named refusal."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return refuse("payload_invalid", f"{key} must be {what}", f"$.{key}")
    return value.strip()


def run_person_change(
    request: FunctionCallRequest,
    change: Callable[[Any, int, int], Dict[str, Any]],
) -> HandlerOutcome:
    """Validate an org-admin call naming one person, then run ``change``.

    ``change(conn, actor_id, caller_actor_id)`` returns the result payload or
    raises :class:`ActorRoleRefused`, which becomes the named refusal.
    """
    if request.target.kind != "global":
        return refuse("target_invalid", f"{request.function} requires a global target")
    raw_caller = (request.actor.actor_id or "").strip()
    if not raw_caller.isdigit():
        return refuse("actor_required", "bind an org-admin actor and retry")
    payload = request.payload or {}
    actor_id = payload.get("actor_id")
    member_email = payload.get("member_email")
    if (actor_id is None) == (member_email is None):
        return refuse("payload_invalid", "pass exactly one of actor_id or member_email")
    if actor_id is not None and (
        isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0
    ):
        return refuse(
            "payload_invalid", "actor_id must be a positive integer", "$.actor_id"
        )
    if member_email is not None and (
        not isinstance(member_email, str) or "@" not in member_email
    ):
        return refuse(
            "payload_invalid", "member_email must be an email address", "$.member_email"
        )
    with db_helpers.connect() as conn:
        try:
            require_control_plane_permission(
                conn, actor_id=int(raw_caller), permission_key=PERM_ORG_ADMIN
            )
        except PermissionDenied as exc:
            return refuse("permission_denied", str(exc))
        try:
            if member_email is not None:
                actor_id = resolve_member_actor(conn, member_email)
            result = change(conn, int(actor_id), int(raw_caller))
        except ActorRoleRefused as exc:
            return refuse(exc.code, str(exc))
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_actor_role_set(request: FunctionCallRequest) -> HandlerOutcome:
    role = text_field(request.payload or {}, "role", "a role name")
    if isinstance(role, HandlerOutcome):
        return role

    def change(conn: Any, actor_id: int, caller: int) -> Dict[str, Any]:
        done = set_actor_org_role(
            conn, actor_id=actor_id, role=role, caller_actor_id=caller, now=utc_now()
        )
        return {
            "actor_id": done.actor_id,
            "role": done.role,
            "previous_roles": done.previous_roles,
            "changed": done.changed,
        }

    return run_person_change(request, change)


def handle_actor_role_remove(request: FunctionCallRequest) -> HandlerOutcome:
    def change(conn: Any, actor_id: int, caller: int) -> Dict[str, Any]:
        previous = remove_actor_org_role(
            conn, actor_id=actor_id, caller_actor_id=caller
        )
        return {
            "actor_id": actor_id,
            "previous_roles": previous,
            "changed": bool(previous),
        }

    return run_person_change(request, change)

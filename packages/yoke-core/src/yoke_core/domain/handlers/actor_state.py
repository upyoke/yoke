"""Org-admin actor enable and disable operation."""

from __future__ import annotations

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN, PermissionDenied
from yoke_core.domain.actor_state import ActorStateRefused, set_actor_enabled
from yoke_core.domain.control_plane_authority import require_control_plane_permission


class ActorStateSetRequest(BaseModel):
    actor_id: int
    enabled: bool
    confirm_system_retirement: bool = False


class ActorStateSetResponse(BaseModel):
    actor_id: int
    status: str
    revoked_tokens: int


def _refuse(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def handle_actor_state_set(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _refuse("target_invalid", "actors.state.set requires a global target")
    raw_caller = (request.actor.actor_id or "").strip()
    if not raw_caller.isdigit():
        return _refuse("actor_required", "bind an org-admin actor and retry")
    payload = request.payload or {}
    actor_id = payload.get("actor_id")
    enabled = payload.get("enabled")
    confirm_system_retirement = payload.get("confirm_system_retirement", False)
    if isinstance(actor_id, bool) or not isinstance(actor_id, int) or actor_id <= 0:
        return _refuse("payload_invalid", "actor_id must be a positive integer")
    if not isinstance(enabled, bool):
        return _refuse("payload_invalid", "enabled must be true or false")
    if not isinstance(confirm_system_retirement, bool) or (
        enabled and confirm_system_retirement
    ):
        return _refuse(
            "payload_invalid",
            "confirm_system_retirement must be a boolean used only when disabling",
        )
    with db_helpers.connect() as conn:
        try:
            require_control_plane_permission(
                conn,
                actor_id=int(raw_caller),
                permission_key=PERM_ORG_ADMIN,
            )
        except PermissionDenied as exc:
            return _refuse("permission_denied", str(exc))
        try:
            revoked = set_actor_enabled(
                conn,
                actor_id=actor_id,
                caller_actor_id=int(raw_caller),
                enabled=enabled,
                now=db_helpers.iso8601_now(),
                confirm_system_retirement=confirm_system_retirement,
            )
        except ActorStateRefused as exc:
            return _refuse("actor_state_refused", str(exc))
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "actor_id": actor_id,
            "status": "active" if enabled else "disabled",
            "revoked_tokens": revoked,
        },
    )

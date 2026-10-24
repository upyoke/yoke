"""Whether a dispatched call carries the actor its side effects require.

The permission gate authorizes a numeric actor id: over https the bearer
token or browser session binds one, and in-process dispatch binds the
calling harness session's actor or this universe's operating actor. A
call that still carries none cannot be authorized or attributed, so a
side-effecting call refuses here with ``actor_required`` instead of running
unchecked. Read-only calls write no attribution and keep running without
an actor.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.function_unresolved_project import permission_error_response
from yoke_core.domain.yoke_function_permission_types import DispatchPermission
from yoke_core.domain.yoke_function_registry import RegistryEntry

ACTOR_REQUIRED = "actor_required"


def numeric_actor_id(value: Any) -> int | None:
    """Return the request's actor id as an int, or ``None`` when absent or non-numeric."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def actor_required_message(function_id: str, received: Any) -> str:
    """Name the missing actor and the ways to supply one."""
    shown = str(received or "").strip()
    received_text = f"non-numeric actor_id {shown!r}" if shown else "no actor_id"
    return compose_refusal(
        f"function {function_id!r} has side effects and this call carries {received_text}, so it cannot be authorized or attributed.",
        recovery=(
            "run it from a registered harness session; on a local universe run `yoke "
            "setup` so this machine records its operating actor; or connect over https "
            "(`yoke env list`). Unset a non-numeric YOKE_ACTOR_ID."
        ),
    )


def missing_actor_refusal(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    permission_key: str | None,
) -> DispatchPermission:
    """Decide an actor-less call: read-only passes, side effects refuse."""
    if not entry.side_effects:
        return DispatchPermission(permission_key, None, None)
    return DispatchPermission(
        permission_key,
        None,
        None,
        error=permission_error_response(
            request,
            entry,
            ACTOR_REQUIRED,
            actor_required_message(entry.function_id, request.actor.actor_id),
        ),
    )


__all__ = [
    "ACTOR_REQUIRED",
    "actor_required_message",
    "missing_actor_refusal",
    "numeric_actor_id",
]

"""Denial-audit sink — ``POST /v1/hooks/denial-audit``.

The relay's client-local subset (``evaluate_local_subset``'s
``LOCAL_STATE_POLICIES``) denies without ever calling ``/hooks/evaluate`` —
the relay client returns immediately on a local deny, skipping the
round-trip its verdict doesn't need — so this is its only way to leave a
durable ``HarnessToolCallDenied`` row. See :mod:`yoke_harness.hooks.denial_relay`
for the client-side caller.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter
from pydantic import BaseModel

from yoke_core.api.http_auth import require_auth_context


router = APIRouter()


class HookDenialAuditRequest(BaseModel):
    """Audit fields for a denial the client already rendered locally."""

    hook: str = ""
    check_id: str = ""
    guard_key: str = ""
    mode: str = "deny"
    reason: str = ""
    command_snippet: str = ""
    session_id: str = ""
    tool_use_id: str = ""
    turn_id: str = ""


@router.post("/hooks/denial-audit")
def post_hooks_denial_audit(
    http_request: Request, request: HookDenialAuditRequest,
) -> JSONResponse:
    """Record the denial. Auth is the same bearer-token middleware as every
    other ``/v1`` route; failures here never surface to the client, which
    already rendered its refusal before this call."""
    require_auth_context(http_request)
    from yoke_core.hooks.denial import emit_denial_event

    try:
        emit_denial_event(
            hook=request.hook,
            check_id=request.check_id,
            reason=request.reason,
            session_id=request.session_id,
            tool_use_id=request.tool_use_id,
            turn_id=request.turn_id,
            command_snippet=request.command_snippet,
            guard_key=request.guard_key,
            mode=request.mode,
        )
    except Exception:
        pass
    return JSONResponse(content={"ok": True})


__all__ = ["HookDenialAuditRequest", "router"]

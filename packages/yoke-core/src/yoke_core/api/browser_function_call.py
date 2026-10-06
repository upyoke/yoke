"""``POST /v1/functions/call`` for a signed-in browser.

The workbench a self-hosted server serves calls this route with its
web-session cookie; middleware has already passed the same-origin check
and verified the session (:mod:`yoke_core.api.web_session_auth`). The
envelope is bound the way every workbench host binds a browser envelope:

* the caller's ``actor`` block is discarded, and the session's actor is
  the identity, with no harness session (a browser has none);
* the target defaults to ``global``;
* sending surfaces are stamped ``web_form``.

The call then dispatches inside :func:`ui_browser_origin`, the process-local
mark that a person at a Yoke browser workbench made it — the same mark the
Local view's proxy sets — so browser-provenance gates such as
merge-candidate review recognise it. The engine's permission model
enforces what the actor may do; there is no browser-specific allowlist.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.session_control.sender_surface import (
    with_web_form_sender_surface,
)
from yoke_contracts.ui_browser_origin import ui_browser_origin
from yoke_core.api.function_call_status import (
    exception_response,
    status_for_response,
)
from yoke_core.api.function_failure_observability import record_function_failure
from yoke_core.api.machine_function_auth import MACHINE_CREDENTIAL_FUNCTIONS
from yoke_core.api.web_session_auth import WebSessionAuthContext
from yoke_core.domain import yoke_function_registry as function_registry
from yoke_core.domain.yoke_function_dispatch import dispatch


def bind_browser_envelope(envelope: Dict[str, Any], *, actor_id: int) -> Dict[str, Any]:
    """Return the envelope the dispatcher sees for a browser call."""
    function_id = str(envelope.get("function") or "")
    target = envelope.get("target")
    bound = {key: value for key, value in envelope.items() if key != "actor"}
    bound["actor"] = {"actor_id": str(actor_id), "session_id": ""}
    bound["target"] = target if isinstance(target, dict) else {"kind": "global"}
    bound["payload"] = with_web_form_sender_surface(
        function_id, envelope.get("payload") or {}
    )
    return bound


def call_function_as_web_session(
    request: Request,
    envelope: Dict[str, Any],
    web: WebSessionAuthContext,
) -> JSONResponse:
    """Dispatch one browser envelope as the web session's actor."""
    bound = bind_browser_envelope(envelope, actor_id=web.actor_id)
    refusal = _credential_refusal(bound)
    if refusal is not None:
        body = refusal.model_dump()
        return JSONResponse(content=body, status_code=status_for_response(body))
    try:
        # ambient_session_id="" (never None): the browser's identity is the
        # session actor, so the dispatcher must not resolve the SERVER
        # process's env/ancestry into a harness session.
        with ui_browser_origin():
            response = dispatch(bound, ambient_session_id="")
    except Exception as exc:
        record_function_failure(request, bound, exc)
        response = exception_response(bound, exc)
    body = response.model_dump()
    return JSONResponse(content=body, status_code=status_for_response(body))


def _credential_refusal(envelope: Dict[str, Any]) -> Optional[FunctionCallResponse]:
    """Refuse calls whose credential a browser session can never be.

    Service-token functions answer only the hosted service token, and
    machine relay functions only that machine's credential. Both are
    credential facts, not permissions, so the actor's permission model
    cannot decide them.
    """
    function_id = str(envelope.get("function") or "")
    entry = function_registry.lookup(function_id)
    if entry is not None and "service_token_required" in entry.guardrails:
        code, message = (
            "permission_denied",
            f"function {function_id!r} requires the hosted service token; "
            "a browser session cannot call it",
        )
    elif function_id in MACHINE_CREDENTIAL_FUNCTIONS:
        code, message = (
            "machine_credential_required",
            f"function {function_id!r} is a machine relay call and needs that "
            "machine's own credential; a browser session cannot make it",
        )
    else:
        return None
    request_id = envelope.get("request_id")
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=str(envelope.get("version") or "v1"),
        request_id=str(request_id) if request_id is not None else None,
        error=FunctionError(code=code, message=message),
    )


__all__ = ["bind_browser_envelope", "call_function_as_web_session"]

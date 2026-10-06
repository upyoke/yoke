"""FastAPI router for the Yoke function-call dispatcher.

Mounts three endpoints under ``/v1``:

- ``POST /functions/call`` — invoke a registered function with an API
  token, or from a signed-in browser's web session. Returns the canonical
  :class:`FunctionCallResponse`. HTTP status reflects the envelope
  (:mod:`yoke_core.api.function_call_status`).
- ``GET /functions/registry`` — list registered function ids + metadata.
- ``GET /functions/schema/{function_id}`` — return the JSON Schema for
  the function's request payload (404 when unregistered).
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRouter

from yoke_core.api.http_auth import (
    HttpAuthContext,
    record_function_authz,
    require_auth_context,
)
from yoke_core.api.browser_function_call import call_function_as_web_session
from yoke_core.api.function_call_status import (
    exception_response,
    status_for_response,
)
from yoke_core.api.function_failure_observability import record_function_failure
from yoke_core.api.observability import record_request_phase
from yoke_core.domain import yoke_function_registry as function_registry
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_dispatch_observability import (
    elapsed_duration_ms,
    handler_duration_ms,
    start_duration_measurement,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_permissions import (
    dispatch_permission_for_request,
)
from yoke_core.domain.yoke_function_registry import (
    RegistryEntry,
    list_entries,
    lookup,
    schema_for,
)
from yoke_core.domain.api_tokens import INITIAL_ADMIN_TOKEN_NAME
from yoke_core.api.machine_function_auth import machine_credential_refusal
from yoke_core.api.launch_machine_actor import bind_actor_for_session
from yoke_core.api.web_session_auth import web_session_context


router = APIRouter()


@router.post("/functions/call")
def call_function(request: Request, envelope: Dict[str, Any]) -> JSONResponse:
    """Invoke a registered function via the dispatcher.

    The HTTP boundary binds actor identity from the verified credential. A
    signed-in browser's call binds the web session's actor
    (:mod:`yoke_core.api.browser_function_call`). Otherwise the bearer
    token's actor replaces any caller-supplied ``actor_id``; ``session_id``
    remains payload-owned because claim/session gates still operate on the
    caller's harness session.
    """
    web = web_session_context(request)
    if web is not None:
        return call_function_as_web_session(request, envelope, web)
    auth = require_auth_context(request)
    bound_envelope = envelope
    # Pass "" (never None) when the envelope carries no session: the
    # caller's ambient identity lives client-side, so the dispatcher must
    # not fall back to resolving the SERVER process's env/ancestry.
    try:
        entry = function_registry.lookup(str(envelope.get("function") or ""))
        service_denial = _service_token_guard_response(envelope, entry, auth)
        if service_denial is not None:
            body = service_denial.model_dump()
            _record_service_token_denial(request, auth, service_denial)
            return JSONResponse(content=body, status_code=status_for_response(body))
        machine_denial = _machine_credential_guard_response(envelope, auth)
        if machine_denial is not None:
            body = machine_denial.model_dump()
            return JSONResponse(content=body, status_code=status_for_response(body))
        bound_envelope, ambient = bind_actor_for_session(envelope, auth)
        _record_pre_dispatch_authz(request, bound_envelope, auth)
        dispatch_started = start_duration_measurement()
        response = dispatch(bound_envelope, ambient_session_id=ambient or "")
        _record_dispatch_overhead(request, dispatch_started)
    except Exception as exc:
        record_function_failure(request, bound_envelope, exc)
        response = exception_response(bound_envelope, exc)
    body = response.model_dump()
    return JSONResponse(content=body, status_code=status_for_response(body))


def _record_dispatch_overhead(request: Request, dispatch_started: float | None) -> None:
    """Report the dispatcher's own cost, with the handler's time removed.

    The handler already reports itself through ``YokeFunctionCalled``; what
    the completed-request log lacked is everything the dispatcher spends
    around it.
    """
    dispatch_ms = elapsed_duration_ms(dispatch_started)
    if dispatch_ms is None:
        return
    record_request_phase(
        request,
        "dispatch_overhead",
        dispatch_ms - (handler_duration_ms() or 0),
    )


def _service_token_guard_response(
    envelope: Dict[str, Any],
    entry: RegistryEntry | None,
    auth: HttpAuthContext,
) -> FunctionCallResponse | None:
    """Deny service-only functions unless the bootstrap service token called."""
    if entry is None or "service_token_required" not in entry.guardrails:
        return None
    if auth.token_name == INITIAL_ADMIN_TOKEN_NAME:
        return None
    request_id = envelope.get("request_id")
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=str(envelope.get("version") or "v1"),
        request_id=str(request_id) if request_id is not None else None,
        error=FunctionError(
            code="permission_denied",
            message=(
                f"function {entry.function_id!r} requires the hosted service token"
            ),
        ),
    )


def _machine_credential_guard_response(
    envelope: Dict[str, Any], auth: HttpAuthContext
) -> FunctionCallResponse | None:
    refusal = machine_credential_refusal(envelope, auth.machine_id)
    if refusal is None:
        return None
    code, message = refusal
    function_id = str(envelope.get("function") or "")
    request_id = envelope.get("request_id")
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=str(envelope.get("version") or "v1"),
        request_id=str(request_id) if request_id is not None else None,
        error=FunctionError(code=code, message=message),
    )


def _record_service_token_denial(
    request: Request,
    auth: HttpAuthContext,
    response: FunctionCallResponse,
) -> None:
    try:
        record_function_authz(
            request,
            auth,
            function_id=response.function,
            request_id=response.request_id,
            project_id=None,
            permission_key="service_token_required",
            outcome="denied",
        )
    except Exception:
        return


def _record_pre_dispatch_authz(
    request: Request,
    envelope: Dict[str, Any],
    auth,
) -> None:
    """Record best-effort non-secret auth telemetry for function calls."""
    try:
        _record_pre_dispatch_authz_checked(request, envelope, auth)
    except Exception:
        return


def _record_pre_dispatch_authz_checked(
    request: Request,
    envelope: Dict[str, Any],
    auth,
) -> None:
    function_id = str(envelope.get("function") or "")
    entry = lookup(function_id)
    permission_key = None
    project_id = None
    outcome = "pre_dispatch"
    request_id = None
    if entry is not None:
        try:
            typed = FunctionCallRequest.model_validate(envelope)
        except Exception:
            typed = None
        if typed is not None:
            request_id = typed.request_id
            permission = dispatch_permission_for_request(entry, typed)
            permission_key = permission.permission_key
            project_id = permission.project_id
            outcome = "allowed" if permission.error is None else "denied"
    record_function_authz(
        request,
        auth,
        function_id=function_id or None,
        request_id=request_id,
        project_id=project_id,
        permission_key=permission_key,
        outcome=outcome,
    )


@router.get("/functions/registry")
def list_registry() -> JSONResponse:
    """Return registered function ids and metadata."""
    entries = []
    for entry in list_entries():
        entries.append(
            {
                "function_id": entry.function_id,
                "version": entry.version,
                "stability": entry.stability,
                "owner_module": entry.owner_module,
                "target_kinds": list(entry.target_kinds),
                "side_effects": list(entry.side_effects),
                "emitted_event_names": list(entry.emitted_event_names),
                "guardrails": list(entry.guardrails),
                "adapter_status": entry.adapter_status,
                "replacement_function_id": entry.replacement_function_id,
                "removal_target_version": entry.removal_target_version,
                "claim_required_kind": entry.claim_required_kind,
            }
        )
    return JSONResponse(content={"functions": entries})


@router.get("/functions/schema/{function_id}")
def get_schema(function_id: str) -> JSONResponse:
    """Return the JSON Schema for ``function_id`` or 404."""
    if lookup(function_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown function {function_id!r}")
    return JSONResponse(content=schema_for(function_id))


@router.get("/cli/manifest")
def get_cli_manifest() -> JSONResponse:
    """Return this env's CLI command/help manifest (grammar + usage).

    Served from the same registries that render `yoke --help` so a
    machine-installed CLI can detect server-side commands its build
    predates (Project install contract help/capability compatibility).
    """
    from yoke_cli.manifest import build_manifest

    return JSONResponse(content=build_manifest())


__all__ = ["router"]

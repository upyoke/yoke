"""FastAPI router for the Yoke function-call dispatcher.

Mounts three endpoints under ``/v1``:

- ``POST /functions/call`` — invoke a registered function. Returns the
  canonical :class:`FunctionCallResponse`. HTTP status reflects the
  envelope: 200 on success, 207 on success-with-warnings, and a typed
  4xx on envelope/registry/claim/idempotency errors.
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
    bind_actor_from_auth,
    record_function_authz,
    require_auth_context,
)
from yoke_core.domain import yoke_function_registry as function_registry
from yoke_core.domain.yoke_function_dispatch import dispatch
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


router = APIRouter()


_ERROR_TO_STATUS: Dict[str, int] = {
    "envelope_invalid": 422,
    "empty_body": 422,
    "invalid_payload": 422,
    "payload_invalid": 422,
    "invalid_field": 422,
    "shrinkage": 422,
    "freeze_lock": 409,
    "validation_failed": 422,
    "function_not_registered": 404,
    "target_not_found": 404,
    "claim_required": 409,
    "operator_override_required": 409,
    "idempotency_key_collision": 409,
    "actor_id_mismatch": 403,
    "actor_session_missing": 403,
    "permission_denied": 403,
    "permission_check_unavailable": 503,
    "render_failed": 500,
    "write_failed": 500,
    "handler_contract": 500,
    "handler_exception": 500,
    # Per-handler validation/gate codes raised by registered handlers.
    "validation_error": 422,
    "unsupported_field": 422,
    "lifecycle_gate_unmet": 422,
    "frozen": 422,
    "precondition_failed": 422,
    "sql_empty": 422,
    "sql_multiple_statements": 422,
    "sql_not_read_only": 422,
    "sql_write_refused": 422,
    "sql_ddl_refused": 422,
    "sql_execution_failed": 422,
}


def _status_for_response(response_envelope: Dict[str, Any]) -> int:
    """Map a function-call response envelope to an HTTP status code."""
    error = response_envelope.get("error")
    if error and error.get("code"):
        return _ERROR_TO_STATUS.get(error["code"], 400)
    if response_envelope.get("warnings"):
        return 207
    return 200


@router.post("/functions/call")
def call_function(request: Request, envelope: Dict[str, Any]) -> JSONResponse:
    """Invoke a registered function via the dispatcher.

    The HTTP boundary binds actor identity from the verified bearer token.
    Caller-supplied ``actor_id`` is discarded before the dispatcher sees the
    envelope; ``session_id`` remains payload-owned because claim/session gates
    still operate on the caller's harness session.
    """
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
            return JSONResponse(content=body, status_code=_status_for_response(body))
        bound_envelope, ambient = bind_actor_from_auth(envelope, auth)
        _record_pre_dispatch_authz(request, bound_envelope, auth)
        response = dispatch(bound_envelope, ambient_session_id=ambient or "")
    except Exception as exc:
        response = _exception_response(bound_envelope, exc)
    body = response.model_dump()
    return JSONResponse(content=body, status_code=_status_for_response(body))


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


def _exception_response(
    envelope: Dict[str, Any],
    exc: Exception,
) -> FunctionCallResponse:
    """Return a typed function envelope for unexpected dispatcher failures."""
    function_id = str(envelope.get("function") or "")
    version = str(envelope.get("version") or "v1")
    request_id = envelope.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        request_id = str(request_id)
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=version,
        request_id=request_id,
        result={},
        warnings=[],
        error=FunctionError(
            code="handler_exception",
            message=(
                f"function call {function_id!r} raised "
                f"{type(exc).__name__}: {exc}"
            ),
        ),
        event_ids=[],
    )


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

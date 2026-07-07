"""Yoke function-call dispatcher — synchronous routing layer.

Single entry point :func:`dispatch` performs envelope validation, registry
lookup, claim verification, idempotency replay, handler dispatch, and
event emission. The dispatcher is *thin* — it does not store data, does
not validate payload shape (handlers do), and does not duplicate domain
logic. Per AGENTS.md ``Architecture Model``, handlers route through
existing domain owners (``backlog_structured_write_op``,
``item_field_transform``, ``epic.task_update_body``, ``sections_cli``,
``path_claims_resolve``, ``service_client_db_claim``, ``lifecycle``,
``backlog_rendering``, ``agents_render``, doctor engines).

Future-concept absorption target: when the execution-journal surface
lands, :func:`dispatch` is absorbed — the call site becomes a
journal-emit + handler-execute pair, and this standalone module is
deleted. The dispatcher is a first pass, not the permanent end-state.

Public surface:

- :func:`dispatch` — synchronous in-process entry point.

Sibling modules:

- :mod:`yoke_function_dispatch_claims` — claim verification helpers.
- :mod:`yoke_function_dispatch_events` — event emission helpers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from pydantic import ValidationError

from yoke_core.domain.yoke_function_actor_identity import (
    bind_actor_identity,
)
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_dispatch_events import (
    emit_called,
    emit_downstream_degraded,
    emit_idempotency_replay,
    emit_permission_denied,
    identity_event_context,
    serialize_payload,
)
from yoke_core.domain.yoke_function_dispatch_observability import (
    dispatch_observation,
)
from yoke_core.domain.yoke_function_dispatch_target import (
    resolve_target_item_ref,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_permissions import dispatch_permission_for_request
from yoke_core.domain.yoke_function_registry import (
    RegistryEntry,
    list_entries,
    lookup,
)

_HANDLERS_REGISTERED = False


def _ensure_handlers_registered() -> None:
    """Lazily register every Yoke function handler on first dispatch.

    Module-level sentinel short-circuits the common in-process repeat
    case. The registry-empty check defends against tests that call
    ``reset_registry_for_tests()`` mid-process: a cleared registry
    re-arms registration even if the sentinel is set.
    """
    global _HANDLERS_REGISTERED
    if _HANDLERS_REGISTERED and list_entries():
        return
    from yoke_core.domain.handlers.__init_register__ import (
        register_all_handlers,
    )
    register_all_handlers()
    _HANDLERS_REGISTERED = True


def _error_response(
    request: Optional[FunctionCallRequest],
    function_id: str,
    version: str,
    code: str,
    message: str,
    *,
    recovery_hint: Optional[str] = None,
    jsonpath: Optional[str] = None,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version=version,
        request_id=request.request_id if request is not None else None,
        result={},
        warnings=[],
        error=FunctionError(
            code=code,
            message=message,
            jsonpath=jsonpath,
            recovery_hint=recovery_hint,
        ),
        event_ids=[],
    )


def _coerce_request(
    request: Any,
) -> Tuple[Optional[FunctionCallRequest], Optional[FunctionCallResponse]]:
    """Return ``(typed_request, error_response)``; one is always None."""
    if isinstance(request, FunctionCallRequest):
        return request, None
    try:
        typed = FunctionCallRequest.model_validate(request)
        return typed, None
    except ValidationError as exc:
        function_id = ""
        version = "v1"
        if isinstance(request, dict):
            function_id = str(request.get("function") or "")
            version = str(request.get("version") or "v1")
        return None, _error_response(
            None, function_id, version, "envelope_invalid", str(exc),
        )


def _idempotency_lookup(
    function_id: str, request_id: str
) -> Optional[Tuple[Dict[str, Any], str]]:
    """Return ``(stored_result, stored_function_id)`` for a prior request.

    Returns ``None`` when no prior call recorded that ``request_id``.
    Exact-match read of ``function_call_ledger`` (rows are written by
    ``emit_called`` alongside the ``YokeFunctionCalled`` emission and
    TTL-pruned by the retention surface). Non-fatal: lookup errors read
    as "no prior call" so dispatch proceeds fresh.
    """
    if not request_id:
        return None
    try:
        from yoke_core.domain.function_call_ledger import lookup_call
    except Exception:
        return None
    return lookup_call(request_id)


def _handle_idempotency(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    identity_context: Optional[Dict[str, Any]] = None,
    permission_key: Optional[str] = None,
    project: Optional[str] = None,
) -> Optional[FunctionCallResponse]:
    """Return a replay/collision response, or None when no prior call exists."""
    if not request.request_id:
        return None
    replay = _idempotency_lookup(entry.function_id, request.request_id)
    if replay is None:
        return None
    stored_result, stored_function = replay
    if stored_function and stored_function != entry.function_id:
        return _error_response(
            request, entry.function_id, entry.version,
            "idempotency_key_collision",
            f"request_id reused across functions "
            f"({stored_function!r} -> {entry.function_id!r})",
        )
    emit_idempotency_replay(
        request, entry,
        identity_context=identity_context,
        permission_key=permission_key,
        project=project,
    )
    return FunctionCallResponse(
        success=True,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result=dict(stored_result),
        warnings=[],
        error=None,
        event_ids=[],
    )


def _build_response(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    outcome: HandlerOutcome,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=outcome.primary_success and outcome.error is None,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result=dict(outcome.result_payload),
        warnings=list(outcome.warnings),
        error=outcome.error,
        event_ids=list(outcome.handler_event_ids),
    )


def _dispatch_impl(
    request: Any,
    *,
    ambient_session_id: Optional[str] = None,
) -> FunctionCallResponse:
    """Route a function call envelope to its registered handler.

    Accepts either a :class:`FunctionCallRequest` or a plain dict (the
    dispatcher coerces dicts to the typed envelope so HTTP and in-process
    callers share one path).

    ``ambient_session_id`` overrides the ambient resolution (env chain,
    then the hook-written process-anchor registry) the actor-identity
    binding layer would otherwise perform. In-process Python callers
    typically leave this ``None`` so the local ambient chain resolves.
    The HTTP boundary supplies the request's session id explicitly
    (possibly ``""``) after bearer-token verification has overwritten
    actor id with the token-owned actor, so the server never consults
    its own environment for the caller's identity. Session id remains
    payload-owned because claim/session gates still operate on the
    caller's harness session.
    """
    _ensure_handlers_registered()
    typed_request, error = _coerce_request(request)
    if error is not None:
        return error
    assert typed_request is not None  # narrows for the type checker

    entry = lookup(typed_request.function)
    if entry is None:
        return _error_response(
            typed_request, typed_request.function, typed_request.version,
            "function_not_registered",
            f"function id {typed_request.function!r} is not registered",
        )

    bound = bind_actor_identity(
        entry, typed_request, ambient_session_id=ambient_session_id,
    )
    if bound.error is not None:
        return bound.error
    assert bound.bound_request is not None  # narrows for the type checker
    typed_request = bound.bound_request
    # Binder findings recorded on every dispatcher event: operator-debug
    # session override (payload session uncorroborated by ambient) and
    # provenance marking for sessions with no harness_sessions row.
    identity_context = identity_event_context(bound) or None

    # Relay contract: clients carry raw item refs; the server resolves
    # them before permission / claim checks so both transports share one
    # resolution authority (yoke_function_dispatch_target).
    ref_error = resolve_target_item_ref(typed_request)
    if ref_error is not None:
        return ref_error

    permission = dispatch_permission_for_request(entry, typed_request)
    if permission.error is not None:
        emit_permission_denied(
            typed_request,
            entry,
            permission_key=permission.permission_key,
            project=permission.project_slug,
            message=permission.error.error.message if permission.error.error else "",
            identity_context=identity_context,
        )
        return permission.error
    if permission.visible_project_ids is not None or permission.project_id is not None:
        options = dict(typed_request.options or {})
        if permission.visible_project_ids is not None:
            options["visible_project_ids"] = list(permission.visible_project_ids)
        if permission.project_id is not None:
            options["authorized_project_id"] = int(permission.project_id)
        typed_request = typed_request.model_copy(update={"options": options})

    idem = _handle_idempotency(
        entry, typed_request,
        identity_context=identity_context,
        permission_key=permission.permission_key,
        project=permission.project_slug,
    )
    if idem is not None:
        return idem

    claim_error = verify_claim(entry, typed_request)
    if claim_error is not None:
        return claim_error

    from yoke_core.domain import project_label_policy

    with project_label_policy.request_overrides(
        typed_request.options.get("label_color_overrides")
    ):
        outcome = entry.handler(typed_request)
    if not isinstance(outcome, HandlerOutcome):
        return _error_response(
            typed_request, entry.function_id, entry.version,
            "handler_contract",
            f"handler for {entry.function_id!r} did not return HandlerOutcome",
        )

    response = _build_response(entry, typed_request, outcome)
    if response.warnings:
        emit_downstream_degraded(
            typed_request, entry, response.warnings,
            identity_context=identity_context,
            permission_key=permission.permission_key,
            project=permission.project_slug,
        )
    payload_bytes, payload_hash = serialize_payload(typed_request.payload)
    emit_called(
        typed_request, entry, outcome, response, payload_bytes, payload_hash,
        identity_context=identity_context,
        permission_key=permission.permission_key,
        project=permission.project_slug,
    )
    return response


def dispatch(
    request: Any,
    *,
    ambient_session_id: Optional[str] = None,
) -> FunctionCallResponse:
    with dispatch_observation(request) as mark_observed:
        response = _dispatch_impl(request, ambient_session_id=ambient_session_id)
        mark_observed(response)
        return response


__all__ = ["dispatch"]

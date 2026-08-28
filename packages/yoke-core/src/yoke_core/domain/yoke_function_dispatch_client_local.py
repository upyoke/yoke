"""Client-local branch of the Yoke function dispatcher.

Kept as a sibling so the control-plane dispatcher remains within the authored
file limit. The branch is deliberately coupled to its parent's coercion and
response builders: client-local functions share the same envelope contract,
but machine possession replaces actor, permission, idempotency, claim, and
event-ledger authority.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallResponse, HandlerOutcome
from yoke_core.domain.function_authz_scope import is_explicit_client_local
from yoke_core.domain.handler_execution_context import invoke_client_local_handler
from yoke_core.domain.yoke_function_dispatch_observability import dispatch_observation
from yoke_core.domain.yoke_function_registry import lookup


def _dispatch(request: Any) -> FunctionCallResponse:
    from yoke_core.domain.yoke_function_dispatch import (
        _build_response,
        _coerce_request,
        _dispatch_impl,
        _ensure_handlers_registered,
        _error_response,
    )

    _ensure_handlers_registered()
    typed_request, error = _coerce_request(request)
    if error is not None:
        return error
    assert typed_request is not None

    entry = lookup(typed_request.function)
    if entry is None:
        return _error_response(
            typed_request,
            typed_request.function,
            typed_request.version,
            "function_not_registered",
            f"function id {typed_request.function!r} is not registered",
        )
    if not is_explicit_client_local(entry.function_id):
        return _dispatch_impl(typed_request)

    outcome = invoke_client_local_handler(entry.handler, typed_request)
    if not isinstance(outcome, HandlerOutcome):
        return _error_response(
            typed_request,
            entry.function_id,
            entry.version,
            "handler_contract",
            f"handler for {entry.function_id!r} did not return HandlerOutcome",
        )
    return _build_response(entry, typed_request, outcome)


def dispatch_client_local(request: Any) -> FunctionCallResponse:
    """Route an explicit client-local function or fall through unchanged."""
    with dispatch_observation(request) as mark_observed:
        response = _dispatch(request)
        mark_observed(response)
        return response


__all__ = ["dispatch_client_local"]

"""Scoped replay and collision decisions for function-call dispatch."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain.yoke_function_dispatch_events import emit_idempotency_replay
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _idempotency_lookup(
    request_id: str,
) -> Optional[Tuple[Dict[str, Any], str, str, str, str]]:
    if not request_id:
        return None
    try:
        from yoke_core.domain.function_call_ledger import lookup_call

        return lookup_call(request_id)
    except Exception:
        return None


def _collision(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result={},
        warnings=[],
        error=FunctionError(code="idempotency_key_collision", message=message),
        event_ids=[],
    )


def handle_idempotency(
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    identity_context: Optional[Dict[str, Any]],
    permission_key: Optional[str],
    project: Optional[str],
    authorization_scope: str,
    payload_checksum: str,
) -> Optional[FunctionCallResponse]:
    """Return a replay/collision response, or None for a fresh request."""
    if "handler_managed_idempotency" in entry.guardrails or not request.request_id:
        return None
    replay = _idempotency_lookup(request.request_id)
    if replay is None:
        return None
    result, function_id, actor_id, scope, checksum = replay
    if function_id and function_id != entry.function_id:
        return _collision(
            request,
            entry,
            "request_id reused across functions "
            f"({function_id!r} -> {entry.function_id!r})",
        )
    if (
        not actor_id
        or actor_id != str(request.actor.actor_id or "")
        or not scope
        or scope != authorization_scope
        or not checksum
        or checksum != payload_checksum
    ):
        return _collision(
            request,
            entry,
            "request_id was already bound to a different authenticated actor, "
            "authorized scope, or canonical payload",
        )
    emit_idempotency_replay(
        request,
        entry,
        identity_context=identity_context,
        permission_key=permission_key,
        project=project,
    )
    return FunctionCallResponse(
        success=True,
        function=entry.function_id,
        version=entry.version,
        request_id=request.request_id,
        result=dict(result),
        warnings=[],
        error=None,
        event_ids=[],
    )


__all__ = ["handle_idempotency"]

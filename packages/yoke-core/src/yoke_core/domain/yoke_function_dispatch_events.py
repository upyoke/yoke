"""Event emission helpers for the function-call dispatcher.

Extracted from :mod:`yoke_function_dispatch` so the dispatcher routing
path stays under file-line budget. All three dispatcher-owned event
names route through :func:`yoke_core.domain.events.emit_event`:

- ``YokeFunctionCalled`` — one per call. Carries function id, version,
  target, payload byte count + checksum, guardrail outcomes, verification
  status, sync status, and the handler's contributed event ids.
- ``DispatcherIdempotencyReplay`` — fired when a prior ``(function,
  request_id)`` is replayed.
- ``DispatcherDownstreamDegraded`` — fired when at least one
  ``FunctionWarning`` lands on the response.

The three event names are seeded into ``event_registry`` by
:mod:`event_registry_seed_yoke_function_call`.

:func:`emit_called` also writes the ``function_call_ledger`` row for a
successful side-effecting call (the idempotency dedup state the dispatcher
replays from) — events stay telemetry; the ledger owns the replay decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.auth_context import auth_context_from_actor
from yoke_core.domain.events import emit_event
from yoke_core.domain.function_call_ledger import record_call
from yoke_core.domain.yoke_function_actor_identity import BoundIdentity
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionWarning,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_registry import RegistryEntry


_KIND = "lifecycle"
_TYPE = "function_call"


def serialize_payload(payload: Dict[str, Any]) -> Tuple[int, str]:
    """Return ``(byte_count, sha256_hex)`` for the canonical-JSON form."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    encoded = canonical.encode("utf-8")
    return len(encoded), hashlib.sha256(encoded).hexdigest()


def identity_event_context(bound: BoundIdentity) -> Dict[str, Any]:
    """Project a :class:`BoundIdentity` to dispatcher event-context keys.

    - ``session_override: true`` (+ the divergent ``ambient_session_id``
      when one resolved) marks the flagged operator-debug path where the
      payload session was not corroborated by ambient resolution.
    - ``provenance_unverified: true`` marks calls whose bound session has
      no ``harness_sessions`` row — an unregistered-session write is
      recorded, never silently trusted (the finding rides the lookup the
      binder already performs; zero extra queries).
    """
    context: Dict[str, Any] = {}
    if bound.explicit_override:
        context["session_override"] = True
        if bound.ambient_session_id:
            context["ambient_session_id"] = bound.ambient_session_id
    if bound.session_registered is False:
        context["provenance_unverified"] = True
    return context


def _item_id_str(req: FunctionCallRequest) -> Any:
    if req.target.item_id is None:
        return None
    return str(req.target.item_id)


def emit_called(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    outcome: HandlerOutcome,
    response: FunctionCallResponse,
    payload_bytes: int,
    payload_hash: str,
    *,
    identity_context: Optional[Dict[str, Any]] = None,
    permission_key: Optional[str] = None,
    project: Optional[str] = None,
    authorization_scope: str,
    idempotency_payload_checksum: str,
) -> None:
    """Emit the canonical ``YokeFunctionCalled`` event for one call.

    ``identity_context`` carries the binder findings from
    :func:`identity_event_context` (operator-debug session override,
    unregistered-session provenance marking). Event attribution
    (``session_id``) always uses the bound session.
    """
    # result_byte_count/result_checksum are deliberately separate scalar
    # keys: when a big result (e.g. strategy render file texts) trips the
    # envelope cap, the value-aware shrink replaces "result" with a
    # marker but the size/checksum scalars survive for audits.
    result_bytes, result_hash = serialize_payload(dict(response.result))
    context = {
        "function": entry.function_id,
        "version": entry.version,
        "target": request.target.model_dump(exclude_none=True),
        "payload_byte_count": payload_bytes,
        "payload_checksum": payload_hash,
        "guardrail_outcomes": list(entry.guardrails),
        "verification_status": (
            "ok" if outcome.primary_success else "failed"
        ),
        "sync_status": "degraded" if response.warnings else "ok",
        "event_ids": list(outcome.handler_event_ids),
        "request_id": request.request_id,
        "result": dict(response.result),
        "result_byte_count": result_bytes,
        "result_checksum": result_hash,
        "intent": request.intent,
    }
    if identity_context:
        context.update(identity_context)
    emit_event(
        "YokeFunctionCalled",
        event_kind=_KIND,
        event_type=_TYPE,
        session_id=request.actor.session_id,
        severity="INFO",
        outcome="completed" if outcome.primary_success else "failed",
        request_id=request.request_id,
        item_id=_item_id_str(request),
        task_num=request.target.task_num,
        project=project or "yoke",
        auth_context=auth_context_from_actor(
            request.actor.actor_id,
            permission_key=permission_key,
        ),
        context=context,
    )
    # Idempotency state rides the same flow as the telemetry emission:
    # the ledger row is what `_idempotency_lookup` replays on request_id
    # reuse. First write wins; calls without a request_id skip, and
    # side-effect-free entries are never ledgered — reads are naturally
    # idempotent and their results (e.g. board.data.get) can be large. Failed
    # outcomes are also never ledgered: the ledger stores only a result dict,
    # not the failure envelope, so replaying one would incorrectly turn it
    # into success and permanently suppress a safe retry.
    if (
        entry.side_effects
        and response.success
        and "handler_managed_idempotency" not in entry.guardrails
    ):
        record_call(
            request.request_id, entry.function_id, dict(response.result),
            actor_id=str(request.actor.actor_id or ""),
            authorization_scope=authorization_scope,
            payload_checksum=idempotency_payload_checksum,
        )


def emit_idempotency_replay(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    *,
    identity_context: Optional[Dict[str, Any]] = None,
    permission_key: Optional[str] = None,
    project: Optional[str] = None,
) -> None:
    """Emit ``DispatcherIdempotencyReplay`` for a deduplicated call."""
    context: Dict[str, Any] = {
        "function": entry.function_id,
        "request_id": request.request_id,
    }
    if identity_context:
        context.update(identity_context)
    emit_event(
        "DispatcherIdempotencyReplay",
        event_kind=_KIND,
        event_type=_TYPE,
        session_id=request.actor.session_id,
        severity="INFO",
        outcome="completed",
        request_id=request.request_id,
        item_id=_item_id_str(request),
        project=project or "yoke",
        auth_context=auth_context_from_actor(
            request.actor.actor_id,
            permission_key=permission_key,
        ),
        context=context,
    )


def emit_downstream_degraded(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    warnings: List[FunctionWarning],
    *,
    identity_context: Optional[Dict[str, Any]] = None,
    permission_key: Optional[str] = None,
    project: Optional[str] = None,
) -> None:
    """Emit ``DispatcherDownstreamDegraded`` for one or more warnings."""
    context: Dict[str, Any] = {
        "function": entry.function_id,
        "warnings": [w.model_dump() for w in warnings],
    }
    if identity_context:
        context.update(identity_context)
    emit_event(
        "DispatcherDownstreamDegraded",
        event_kind=_KIND,
        event_type=_TYPE,
        session_id=request.actor.session_id,
        severity="WARN",
        outcome="degraded",
        request_id=request.request_id,
        item_id=_item_id_str(request),
        project=project or "yoke",
        auth_context=auth_context_from_actor(
            request.actor.actor_id,
            permission_key=permission_key,
        ),
        context=context,
    )


def emit_permission_denied(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    *,
    permission_key: Optional[str],
    project: Optional[str],
    message: str,
    identity_context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit telemetry for a dispatcher permission refusal."""
    context: Dict[str, Any] = {
        "function": entry.function_id,
        "request_id": request.request_id,
        "target": request.target.model_dump(exclude_none=True),
        "authz": "denied",
        "message": message,
    }
    if identity_context:
        context.update(identity_context)
    emit_event(
        "YokeFunctionPermissionDenied",
        event_kind=_KIND,
        event_type=_TYPE,
        session_id=request.actor.session_id,
        severity="WARN",
        outcome="denied",
        request_id=request.request_id,
        item_id=_item_id_str(request),
        task_num=request.target.task_num,
        project=project or "yoke",
        auth_context=auth_context_from_actor(
            request.actor.actor_id,
            permission_key=permission_key,
        ),
        context=context,
    )


__all__ = [
    "identity_event_context",
    "serialize_payload",
    "emit_called",
    "emit_idempotency_replay",
    "emit_downstream_degraded",
    "emit_permission_denied",
]

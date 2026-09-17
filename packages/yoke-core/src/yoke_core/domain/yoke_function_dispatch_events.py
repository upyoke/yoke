"""Event emission helpers for the function-call dispatcher.

Extracted from :mod:`yoke_function_dispatch` so the dispatcher routing
path stays under file-line budget. All three dispatcher-owned event
names route through :func:`yoke_core.domain.events.emit_event`:

- ``YokeFunctionCalled`` — one per call. Carries compact metadata only:
  function id, version, target, payload and result byte counts plus
  checksums, guardrail outcomes, verification status, sync status, the
  handler's contributed event ids, and — when the call failed — bounded
  error details. The result document rides it only under a live scoped
  debug campaign (:func:`detailed_capture_context`); routinely it does
  not, and the caller's response plus ``function_call_ledger`` remain
  where the full result lives.
- ``DispatcherIdempotencyReplay`` — fired when a prior ``(function,
  request_id)`` is replayed.
- ``DispatcherDownstreamDegraded`` — fired when at least one
  ``FunctionWarning`` lands on the response.

The three event names are seeded into ``event_registry`` by
:mod:`event_registry_seed_yoke_function_call`.

:func:`emit_called` also writes the ``function_call_ledger`` row for a
successful side-effecting call (the idempotency dedup state the dispatcher
replays from) — events stay telemetry; the ledger owns the replay decision.
The ledger write runs BEFORE the emission so a telemetry failure can never
skip it: ``emit_event`` re-raises ``RetiredEventNameError``, and with the
old ordering that raise left a committed mutation with no replay row.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.api.observability import debug_detail_allowed, service_name
from yoke_core.domain.auth_context import auth_context_from_actor
from yoke_core.domain.events import emit_event
from yoke_core.domain.function_call_ledger import record_call
from yoke_core.domain.session_action_attribution import record_session_action
from yoke_core.domain.yoke_function_actor_identity import BoundIdentity
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionWarning,
    HandlerOutcome,
)
from yoke_core.domain.yoke_function_dispatch_failure_context import (
    clip,
    clipped_warning,
    error_event_context,
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


def detailed_capture_context(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    response: FunctionCallResponse,
) -> Dict[str, Any]:
    """Return the full result, but only under a live debug campaign.

    Default is off: with no campaign armed, or one that is expired, out
    of scope, or past its record cap,
    :func:`yoke_core.api.observability.debug_detail_allowed` answers false
    and the routine event keeps the compact shape. Called exactly once
    per dispatch, because a true answer consumes one unit of the
    campaign's record budget.
    """
    if not debug_detail_allowed({
        "function": entry.function_id,
        "session_id": request.actor.session_id,
        "request_id": request.request_id,
        "service": service_name(),
    }):
        return {}
    return {"result": dict(response.result)}


def emit_called(
    request: FunctionCallRequest,
    entry: RegistryEntry,
    outcome: HandlerOutcome,
    response: FunctionCallResponse,
    payload_bytes: int,
    payload_hash: str,
    *,
    duration_ms: Optional[int] = None,
    identity_context: Optional[Dict[str, Any]] = None,
    permission_key: Optional[str] = None,
    project: Optional[str] = None,
    authorization_scope: str,
    idempotency_payload_checksum: str,
    claim_verification: Dict[str, Any],
) -> None:
    """Emit the canonical ``YokeFunctionCalled`` event for one call.

    ``identity_context`` carries the binder findings from
    :func:`identity_event_context` (operator-debug session override,
    unregistered-session provenance marking). Event attribution
    (``session_id``) always uses the bound session.
    """
    # Routine telemetry carries the result's SIZE and DIGEST, never the
    # document. Over the most recent 2,000 production calls the copied
    # result was 8,876,530 of 11,982,526 envelope characters (74%), and
    # no reader consumed it: the caller already holds the result on the
    # response, and a ledgered call keeps it in ``function_call_ledger``.
    # Exceptional detailed capture belongs behind a scoped, expiring,
    # record-capped debug campaign (:func:`debug_detail_allowed` below),
    # never in the routine INFO event.
    result_bytes, result_hash = serialize_payload(dict(response.result))
    context = {
        "function": entry.function_id,
        "version": entry.version,
        "target": request.target.model_dump(exclude_none=True),
        "payload_byte_count": payload_bytes,
        "payload_checksum": payload_hash,
        "side_effects": list(entry.side_effects),
        "claim_required_kind": entry.claim_required_kind,
        "claim_verification": dict(claim_verification),
        "guardrail_outcomes": list(entry.guardrails),
        "verification_status": (
            "ok" if outcome.primary_success else "failed"
        ),
        "sync_status": "degraded" if response.warnings else "ok",
        "event_ids": list(outcome.handler_event_ids),
        "request_id": request.request_id,
        "result_byte_count": result_bytes,
        "result_checksum": result_hash,
        "intent": request.intent,
        "duration_ms": duration_ms,
    }
    if identity_context:
        context.update(identity_context)
    context.update(error_event_context(response.error))
    context.update(detailed_capture_context(request, entry, response))
    # Idempotency state is the operational owner of the replay decision,
    # so it is written BEFORE the disposable telemetry below: `emit_event`
    # re-raises RetiredEventNameError, and emitting first let that raise
    # strand a committed mutation with no ledger row. First write wins;
    # calls without a request_id skip, and side-effect-free entries are
    # never ledgered — reads are naturally idempotent and their results
    # (e.g. board.data.get) can be large. Failed outcomes are also never
    # ledgered: the ledger stores only a result dict, not the failure
    # envelope, so replaying one would incorrectly turn it into success
    # and permanently suppress a safe retry.
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
        duration_ms=duration_ms,
        auth_context=auth_context_from_actor(
            request.actor.actor_id,
            permission_key=permission_key,
        ),
        context=context,
    )
    # A call that acted on another session also belongs in THAT session's
    # history, attributed to the caller's actor — otherwise a worker's own
    # history cannot say who woke, held, or ended it.
    record_session_action(request, entry.function_id, response, project=project)


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
    """Emit ``DispatcherDownstreamDegraded`` for one or more warnings.

    Each warning's free-form ``detail`` is clipped by
    :func:`yoke_function_dispatch_failure_context.clipped_warning`.
    """
    context: Dict[str, Any] = {
        "function": entry.function_id,
        "warnings": [clipped_warning(w) for w in warnings],
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
        "message": clip(message)[0],
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
    "detailed_capture_context",
    "identity_event_context",
    "serialize_payload",
    "emit_called",
    "emit_idempotency_replay",
    "emit_downstream_degraded",
    "emit_permission_denied",
]

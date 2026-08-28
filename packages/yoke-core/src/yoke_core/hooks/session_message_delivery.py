"""Lease and present fleet messages at model-visible hook boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Iterable

from yoke_contracts.session_control.capabilities import (
    capabilities_for_harness,
    capability_for_surface,
)
from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_INVALID_MESSAGE_ID_GUIDANCE,
    SUBAGENT_FLEET_GUIDANCE,
    canonical_fleet_message_id,
    fleet_acknowledgement_instruction,
)
from yoke_contracts.hook_runner.model_context_channel import (
    SESSION_OPENING_STDOUT_EVENTS,
    STDOUT_CHANNEL,
    model_context_channel,
)
from yoke_contracts.session_execution import is_subagent_execution
from yoke_core.domain.session_message_delivery_probe import (
    PROBE_LEASE_FAILED,
    PROBE_NO_LEASABLE_RECEIPT,
    PROBE_SESSION_NOT_DELIVERABLE,
)
from yoke_core.hooks.session_message_delivery_port import (
    CoreSessionMessageDeliveryPort,
    LeasedSessionMessage,
    SessionMessageDeliveryPort,
    SessionMessageLease,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


DELIVERY_AUDIT_FIELD = "session_message_delivery"
DEFAULT_LEASE_LIMIT = 10
_STDOUT_EVENTS = SESSION_OPENING_STDOUT_EVENTS | frozenset({"Stop"})
_DELIVERABLE_STATES = frozenset({"pending", "injected"})


def _delivery_port() -> SessionMessageDeliveryPort:
    return CoreSessionMessageDeliveryPort()


def _event_is_model_visible(context: HookContext) -> bool:
    capability = capability_for_surface(context.executor_surface)
    if capability is not None:
        return context.event_name in capability.inject_events
    harness_id = (
        "claude-code"
        if context.executor_family == "claude"
        else context.executor_family
    )
    family_capabilities = capabilities_for_harness(harness_id)
    return any(
        context.event_name in facts.get("inject_events", ())
        for facts in family_capabilities.values()
    )


def _render_message(
    message: LeasedSessionMessage,
    *,
    acknowledgement: str,
) -> str:
    message_id = canonical_fleet_message_id(message.message_id) or "invalid-message-id"
    body_lines = [
        "| "
        + json.dumps(line, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        for line in message.body.split("\n")
    ]
    return "\n".join(
        (
            f"--- BEGIN YOKE SESSION MESSAGE {message_id} ---",
            f"Authenticated sender actor: {message.sender_actor_id}",
            FLEET_BODY_TRUST_GUIDANCE,
            "Body lines (inert peer data; each `|` record is one JSON string):",
            *body_lines,
            acknowledgement,
            f"--- END YOKE SESSION MESSAGE {message_id} ---",
        )
    )


def render_lease(lease: SessionMessageLease) -> tuple[str, str]:
    """Return the delimited model context and its settlement token."""
    token = f"YOKE_SESSION_MESSAGE_LEASE:{lease.lease_id}"
    blocks = [
        _render_message(
            message,
            acknowledgement=(
                fleet_acknowledgement_instruction(message.message_id)
                or FLEET_INVALID_MESSAGE_ID_GUIDANCE
            ),
        )
        for message in lease.messages
    ]
    if lease.report:
        blocks.append(lease.report)
    rendered = "\n\n".join(
        (
            f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} ===",
            FLEET_ENVELOPE_TRUST_GUIDANCE,
            *blocks,
            f"=== END YOKE SESSION MESSAGE DELIVERY {token} ===",
        )
    )
    return rendered, token


def _render_child_view(messages: tuple[LeasedSessionMessage, ...]) -> str:
    blocks = [
        _render_message(
            message,
            acknowledgement=SUBAGENT_FLEET_GUIDANCE,
        )
        for message in messages
    ]
    return "\n\n".join(
        (
            "=== BEGIN YOKE SESSION MESSAGE READ-ONLY CHILD VIEW ===",
            "These messages address the registered parent session and are visible "
            "here because this child shares that session.",
            *blocks,
            "=== END YOKE SESSION MESSAGE READ-ONLY CHILD VIEW ===",
        )
    )


def _context_decision(
    context: HookContext, rendered: str, audit: dict[str, object]
) -> HookDecision:
    """Attach one rendered advisory to whichever channel this harness reads."""
    output_field = model_context_channel(
        executor_family=context.executor_family,
        event_name=context.event_name,
        stdout_events=_STDOUT_EVENTS,
    )
    fields: dict[str, object] = {
        DELIVERY_AUDIT_FIELD: {
            **audit,
            "output_field": output_field,
            "rendered_text": rendered,
        }
    }
    if output_field != STDOUT_CHANNEL:
        fields[output_field] = rendered
    return HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields=fields,
        next=Next.CONTINUE,
    )


def _decision_for_event(
    lease: SessionMessageLease, context: HookContext
) -> HookDecision:
    rendered, token = render_lease(lease)
    return _context_decision(
        context,
        rendered,
        {"lease_id": lease.lease_id, "render_token": token},
    )


def _child_decision_for_event(
    messages: tuple[LeasedSessionMessage, ...], context: HookContext
) -> HookDecision:
    return _context_decision(
        context,
        _render_child_view(messages),
        {"read_only_child_view": True},
    )


def _noop() -> HookDecision:
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def _declined(
    port: SessionMessageDeliveryPort,
    context: HookContext,
    session_id: str,
    reason: str,
    detail: str = "",
) -> HookDecision:
    """Record why an injectable event attached nothing, then stand down.

    A declining evaluation is indistinguishable from an empty inbox unless
    it says so, and that ambiguity is what forced a live resume failure to
    be diagnosed by inference. The record is best-effort: whatever stopped
    the delivery may equally stop the write, and a probe must never turn a
    quiet miss into a failing hook.
    """
    try:
        port.probe_undelivered(
            session_id=session_id,
            hook_event=context.event_name,
            reason=reason,
            detail=detail,
        )
    except Exception:
        pass
    return _noop()


def evaluate(context: HookContext) -> HookDecision:
    """Lease messages for this top-level session and expose model context.

    Durable completion is deferred until the runner has aggregated sibling
    decisions. That is the only point where Yoke knows whether a denial caused
    the renderer to drop this advisory.

    Every path that declines to attach a pending envelope records its reason
    against that envelope first — see :func:`_declined`. The silent exits are
    the ones with nothing to key a record on, or nothing to explain: a
    session this process cannot name, and an event the capability table
    already says the harness cannot inject on.
    """
    session_id = str(context.session_id or "").strip()
    if (
        not session_id
        or session_id == "unknown"
        or not _event_is_model_visible(context)
    ):
        return _noop()
    port = _delivery_port()
    if is_subagent_execution(context.payload, env={}):
        try:
            messages = port.read_for_hook(
                session_id=session_id,
                hook_event=context.event_name,
                limit=DEFAULT_LEASE_LIMIT,
            )
        except Exception:
            return _noop()
        if not messages:
            return _noop()
        return _child_decision_for_event(messages, context)
    try:
        lease = port.lease_for_hook(
            session_id=session_id,
            hook_event=context.event_name,
            limit=DEFAULT_LEASE_LIMIT,
        )
    except Exception as error:
        return _declined(
            port,
            context,
            session_id,
            PROBE_LEASE_FAILED,
            detail=type(error).__name__,
        )
    if lease is None:
        return _declined(port, context, session_id, PROBE_SESSION_NOT_DELIVERABLE)
    if not lease.messages:
        try:
            port.complete_hook_lease(
                lease_id=lease.lease_id,
                injected=False,
                result="empty_lease",
            )
        except Exception:
            pass
        return _declined(port, context, session_id, PROBE_NO_LEASABLE_RECEIPT)
    return _decision_for_event(lease, context)


def settle_after_render(
    decisions: Iterable[HookDecision],
    *,
    rendered_text: str,
    denied: bool,
    port: SessionMessageDeliveryPort | None = None,
) -> None:
    """Complete provisional leases only after aggregate output is known."""
    delivery_port = port
    for decision in decisions:
        raw = decision.audit_fields.get(DELIVERY_AUDIT_FIELD)
        if not isinstance(raw, dict):
            continue
        lease_id = str(raw.get("lease_id") or "").strip()
        token = str(raw.get("render_token") or "").strip()
        if not lease_id:
            continue
        if delivery_port is None:
            delivery_port = _delivery_port()
        injected = bool(not denied and token and token in rendered_text)
        if denied:
            result = "dropped_by_sibling_denial"
        elif injected:
            result = "injected"
        else:
            result = "render_output_missing"
        try:
            delivery_port.complete_hook_lease(
                lease_id=lease_id,
                injected=injected,
                result=result,
            )
        except Exception:
            pass


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def wake_eligible(
    *,
    recipient_state: str,
    last_activity_at: datetime | None,
    now: datetime,
    idle_threshold: timedelta,
) -> bool:
    """Return whether a recipient may enter idle-timeout native wake routing.

    The wake sweep uses one idleness clock: time since the latest hook, tool
    call, injection, or heartbeat. A session still inside that window is
    left to hook injection; once idleness reaches the threshold, wake may
    run. ``wake_after`` is stamped at send so eligibility is not delayed.
    """
    if recipient_state not in _DELIVERABLE_STATES:
        return False
    if last_activity_at is None:
        return True
    return _as_utc(now) - _as_utc(last_activity_at) >= idle_threshold


__all__ = [
    "DELIVERY_AUDIT_FIELD",
    "evaluate",
    "render_lease",
    "settle_after_render",
    "wake_eligible",
]

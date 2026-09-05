"""Lease and present fleet messages at model-visible hook boundaries."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from yoke_contracts.hook_context_compose import (
    FLEET_REPORT_CONTEXT_FIELD,
    POINTER_BEGIN,
    compose_context_list,
    overflow_lease_marker,
    reply_is_well_formed,
    token_delivered,
)
from yoke_contracts.hook_runner.model_context_channel import (
    SESSION_OPENING_STDOUT_EVENTS,
    STDOUT_CHANNEL,
    model_context_channel,
)
from yoke_contracts.session_control.capabilities import (
    capabilities_for_harness,
    capability_for_surface,
)
from yoke_contracts.session_control.wake_delivery import HOOK_INJECTED_RESULT
from yoke_contracts.session_execution import is_subagent_execution
from yoke_core.domain.session_message_delivery_probe import (
    PROBE_LEASE_FAILED,
    PROBE_NO_LEASABLE_RECEIPT,
    PROBE_SESSION_NOT_DELIVERABLE,
)
from yoke_core.hooks.fleet_watcher_presence import maybe_append_fleet_watcher_nudge
from yoke_core.hooks.session_message_delivery_port import (
    CoreSessionMessageDeliveryPort,
    LeasedSessionMessage,
    SessionMessageDeliveryPort,
    SessionMessageLease,
)
from yoke_core.hooks.session_message_report_only import report_only_decision
from yoke_core.hooks.session_message_rendering import (
    render_child_view,
    render_lease,
)
from yoke_core.hooks.session_message_wake_eligibility import wake_eligible
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


DELIVERY_AUDIT_FIELD = "session_message_delivery"
DEFAULT_LEASE_LIMIT = 10
_STDOUT_EVENTS = SESSION_OPENING_STDOUT_EVENTS | frozenset({"Stop"})


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


def _context_decision(
    context: HookContext,
    rendered: str,
    audit: dict[str, object],
    extra_fields: dict[str, object] | None = None,
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
    if extra_fields:
        fields.update(extra_fields)
    return HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields=fields,
        next=Next.CONTINUE,
    )


def _decision_for_event(
    lease: SessionMessageLease, context: HookContext
) -> HookDecision:
    lease = replace(
        lease,
        report=maybe_append_fleet_watcher_nudge(
            lease.report,
            session_id=str(context.session_id or ""),
            executor_family=context.executor_family,
            remote=context.remote,
        ),
    )
    rendered, token = render_lease(
        lease,
        session_id=str(context.session_id or ""),
    )
    audit: dict[str, object] = {"lease_id": lease.lease_id, "render_token": token}
    extra: dict[str, object] = {}
    if lease.report:
        audit.update(
            report_session_id=str(context.session_id or ""),
            report_fingerprint=lease.report_fingerprint,
            report_claimed_at=lease.report_claimed_at,
            report_not_after=lease.report_not_after,
        )
        output_field = model_context_channel(
            executor_family=context.executor_family,
            event_name=context.event_name,
            stdout_events=_STDOUT_EVENTS,
        )
        if output_field == STDOUT_CHANNEL:
            # The message already committed to this event's raw-stdout wire
            # format; a report riding the additionalContext channel beside it
            # would concatenate a JSON envelope with raw text into one
            # invalid reply. Fold both into the single coherent block this
            # event actually reads, keeping compose_hook_context's
            # delivery-then-report order and inline cap.
            rendered = compose_context_list(
                [rendered, lease.report], harness_id=context.executor_family
            )
        else:
            extra[FLEET_REPORT_CONTEXT_FIELD] = lease.report
    return _context_decision(context, rendered, audit, extra_fields=extra or None)


def _child_decision_for_event(
    messages: tuple[LeasedSessionMessage, ...], context: HookContext
) -> HookDecision:
    return _context_decision(
        context,
        render_child_view(messages),
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
        if lease.lease_id:
            try:
                port.complete_hook_lease(
                    lease_id=lease.lease_id,
                    injected=False,
                    result="empty_lease",
                )
            except Exception:
                pass
        if lease.report:
            # An empty inbox is not the same question as an empty report: a
            # steering session owed a report still receives it here.
            return report_only_decision(
                lease,
                context,
                delivery_audit_field=DELIVERY_AUDIT_FIELD,
                stdout_events=_STDOUT_EVENTS,
            )
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
        if lease_id:
            if delivery_port is None:
                delivery_port = _delivery_port()
            token = str(raw.get("render_token") or "").strip()
            # A substring match alone is not proof of delivery: a report
            # envelope followed by an unrelated raw message body satisfies
            # it while the harness's own parser never reaches the second
            # value. token_delivered also checks the reply parses cleanly.
            injected = not denied and token_delivered(rendered_text, token)
            overflow = bool(
                POINTER_BEGIN in rendered_text
                and overflow_lease_marker(lease_id) in rendered_text
            )
            if overflow:
                injected = False
            if denied:
                result = "dropped_by_sibling_denial"
            elif overflow:
                result = "inline_overflow"
            elif injected:
                result = HOOK_INJECTED_RESULT
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
        fingerprint = str(raw.get("report_fingerprint") or "").strip()
        # A malformed or denied reply must not spend the report's interval:
        # the composed candidate is best-effort until this confirms the
        # reply that carried it was actually well-formed and undenied, so a
        # dropped report leaves the next hook free to retry instead of
        # waiting out a whole interval for nothing.
        if fingerprint and not denied and reply_is_well_formed(rendered_text):
            if delivery_port is None:
                delivery_port = _delivery_port()
            try:
                delivery_port.confirm_report_delivered(
                    session_id=str(raw.get("report_session_id") or ""),
                    fingerprint=fingerprint,
                    claimed_at=str(raw.get("report_claimed_at") or ""),
                    not_after=str(raw.get("report_not_after") or ""),
                )
            except Exception:
                pass


__all__ = [
    "DELIVERY_AUDIT_FIELD",
    "evaluate",
    "settle_after_render",
    "wake_eligible",
]

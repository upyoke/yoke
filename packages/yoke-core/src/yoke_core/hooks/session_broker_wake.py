"""Present one same-machine broker request at a live peer hook."""

from __future__ import annotations

from collections.abc import Iterable

from yoke_contracts.session_control.capabilities import (
    capabilities_for_harness,
    capability_for_surface,
)
from yoke_contracts.hook_runner.model_context_channel import (
    SESSION_OPENING_STDOUT_EVENTS,
    STDOUT_CHANNEL,
    model_context_channel,
)
from yoke_contracts.session_execution import is_subagent_execution
from yoke_core.hooks.session_broker_wake_port import (
    BrokerWakeLease,
    CoreSessionBrokerWakePort,
    SessionBrokerWakePort,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


BROKER_AUDIT_FIELD = "session_broker_wake"
_STDOUT_EVENTS = SESSION_OPENING_STDOUT_EVENTS


def _broker_port() -> SessionBrokerWakePort:
    return CoreSessionBrokerWakePort()


def _event_is_model_visible(context: HookContext) -> bool:
    if is_subagent_execution(context.payload):
        return False
    if context.event_name in {"Stop", "SessionEnd"}:
        return False
    capability = capability_for_surface(context.executor_surface)
    if capability is not None:
        return context.event_name in capability.inject_events
    harness_id = (
        "claude-code"
        if context.executor_family == "claude"
        else context.executor_family
    )
    return any(
        context.event_name in facts.get("inject_events", ())
        for facts in capabilities_for_harness(harness_id).values()
    )


def _render(lease: BrokerWakeLease) -> tuple[str, str]:
    token = f"YOKE_BROKER_WAKE_LEASE:{lease.lease_id}"
    text = "\n".join(
        (
            f"=== BEGIN YOKE ONE-HOP WAKE {token} ===",
            "A stopped session on this machine needs a native wake.",
            "This request contains no message body and grants no extra authority.",
            f"Run exactly once now: {lease.command}",
            "Do not forward or broker this request to another session.",
            f"=== END YOKE ONE-HOP WAKE {token} ===",
        )
    )
    return text, token


def evaluate(context: HookContext) -> HookDecision:
    session_id = str(context.session_id or "").strip()
    if (
        not session_id
        or session_id == "unknown"
        or not _event_is_model_visible(context)
    ):
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    port = _broker_port()
    try:
        lease = port.lease_for_hook(
            broker_session_id=session_id,
            hook_event=context.event_name,
        )
    except Exception:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    if lease is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    rendered, token = _render(lease)
    output_field = model_context_channel(
        executor_family=context.executor_family,
        event_name=context.event_name,
        stdout_events=_STDOUT_EVENTS,
    )
    fields = {
        BROKER_AUDIT_FIELD: {
            "attempt_id": lease.attempt_id,
            "lease_id": lease.lease_id,
            "render_token": token,
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


def settle_after_render(
    decisions: Iterable[HookDecision],
    *,
    rendered_text: str,
    denied: bool,
    port: SessionBrokerWakePort | None = None,
) -> None:
    broker_port = port or _broker_port()
    for decision in decisions:
        raw = decision.audit_fields.get(BROKER_AUDIT_FIELD)
        if not isinstance(raw, dict):
            continue
        lease_id = str(raw.get("lease_id") or "").strip()
        token = str(raw.get("render_token") or "").strip()
        if not lease_id:
            continue
        delivered = bool(not denied and token and token in rendered_text)
        result = (
            "dropped_by_sibling_denial"
            if denied
            else "injected"
            if delivered
            else "render_output_missing"
        )
        try:
            broker_port.complete_hook_lease(
                lease_id=lease_id,
                delivered=delivered,
                result=result,
            )
        except Exception:
            pass


__all__ = ["BROKER_AUDIT_FIELD", "evaluate", "settle_after_render"]

"""Attach a steering report to a hook delivery with no pending message.

``session_message_delivery.evaluate`` used to decline outright whenever a
session's inbox was empty, even when a fleet report was independently owed —
so a steering session with nothing queued never saw its report at all. This
renders that report-only reply, mirroring message delivery's own channel
routing (raw stdout for a raw-stdout harness on its opening events,
``additionalContext`` otherwise) without rendering a hollow message envelope
for zero messages.
"""

from __future__ import annotations

from yoke_contracts.hook_context_compose import (
    FLEET_REPORT_CONTEXT_FIELD,
    compose_context_list,
)
from yoke_contracts.hook_runner.model_context_channel import (
    STDOUT_CHANNEL,
    model_context_channel,
)
from yoke_core.hooks.fleet_watcher_presence import maybe_append_fleet_watcher_nudge
from yoke_core.hooks.session_message_delivery_port import SessionMessageLease
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


def report_only_decision(
    lease: SessionMessageLease,
    context: HookContext,
    *,
    delivery_audit_field: str,
    stdout_events: frozenset[str],
) -> HookDecision:
    """Render ``lease.report`` alone, carried by no message.

    The caller passes its own ``DELIVERY_AUDIT_FIELD``/stdout-event scope so
    this module names no magic values of its own — settlement still finds
    everything it needs (``report_fingerprint``/``report_claimed_at``/
    ``report_not_after``/``report_session_id``) under that one field.
    """
    report = maybe_append_fleet_watcher_nudge(
        lease.report,
        session_id=str(context.session_id or ""),
        executor_family=context.executor_family,
        remote=context.remote,
    )
    output_field = model_context_channel(
        executor_family=context.executor_family,
        event_name=context.event_name,
        stdout_events=stdout_events,
    )
    # A bare report on the stdout channel still routes through the shared
    # compose/cap pass — nothing upstream enforces this harness's inline
    # budget on stdout-channel text the way ``composed_additional_context``
    # already does for the additionalContext channel.
    rendered_text = (
        compose_context_list([report], harness_id=context.executor_family)
        if output_field == STDOUT_CHANNEL
        else ""
    )
    audit = {
        "lease_id": "",
        "render_token": "",
        "report_session_id": str(context.session_id or ""),
        "report_fingerprint": lease.report_fingerprint,
        "report_claimed_at": lease.report_claimed_at,
        "report_not_after": lease.report_not_after,
        "output_field": output_field,
        "rendered_text": rendered_text,
    }
    fields: dict[str, object] = {delivery_audit_field: audit}
    if output_field != STDOUT_CHANNEL:
        fields[FLEET_REPORT_CONTEXT_FIELD] = report
    return HookDecision(outcome=Outcome.AUDIT_ONLY, audit_fields=fields, next=Next.CONTINUE)


__all__ = ["report_only_decision"]

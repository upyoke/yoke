"""Show a reactivated session its slim resume block, once per reactivation.

A session whose claims were released while it was away carries a pending
resume notice on its control-plane row. The first session-opening event
after the reactivation renders that notice
(:func:`yoke_core.domain.sessions_resume_block.render_and_mark`), which
also clears it, so later events render nothing.

The notice lives in the control plane, so this policy runs wherever the
chain runs (``SERVER`` in :mod:`yoke_contracts.hook_runner.policy_home`):
in-process on a local universe, and on the authority over HTTPS. The block
reaches the model on the reply channel the harness reads
(:mod:`yoke_contracts.hook_runner.model_context_channel`).
"""

from __future__ import annotations

from yoke_contracts.hook_runner.model_context_channel import (
    SESSION_OPENING_STDOUT_EVENTS,
    STDOUT_CHANNEL,
    model_context_channel,
)

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

_NOOP = HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def evaluate(context: HookContext) -> HookDecision:
    """Render and clear the session's pending resume notice, if any."""
    session_id = context.session_id or ""
    if (
        context.event_name not in SESSION_OPENING_STDOUT_EVENTS
        or not session_id
        or session_id == "unknown"
    ):
        return _NOOP
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.sessions_resume_block import render_and_mark

    conn = connect()
    try:
        block = render_and_mark(conn, session_id, harness_event=context.event_name)
    finally:
        conn.close()
    if not block:
        return _NOOP
    channel = model_context_channel(
        executor_family=context.executor_family or "",
        event_name=context.event_name,
        stdout_events=SESSION_OPENING_STDOUT_EVENTS,
    )
    field = "stdout" if channel == STDOUT_CHANNEL else channel
    return HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields={field: block},
        next=Next.CONTINUE,
    )


__all__ = ["evaluate"]

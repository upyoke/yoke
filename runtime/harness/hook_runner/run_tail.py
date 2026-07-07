"""Post-chain tail for ``run_event``: batched telemetry flush + lifecycle.

One budget-gated tail step over a single reused connection — the decision
is already rendered before this runs, so a slow or skipped tail can never
suppress a deny. Carries the dispatch telemetry record, the
ensure-register-on-first-sight tuple (tool-call hooks are the only
guaranteed event class; remote evaluation registers the DB half — with
the request executor honored and the verified token actor bound — while
the hook relay anchors client-side), and the remote session lifecycle
(Stop / SessionEnd end cleanup + SessionStart stale reap): the relay
client evaluates ``session_dispatch`` locally, but on no-checkout
machines that evaluation no-ops (not a Yoke target), so the server-side
lifecycle remains the DB-effective half there. The relay's client-side
subset run sets ``flush_tail=False`` and skips this step entirely — the
server's run owns it for relayed events.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def _str_or(value: Any, default: Optional[str] = None) -> Optional[str]:
    return value if isinstance(value, str) else default


def flush_run_tail(
    *,
    event_name: str,
    context,
    chain_length: int,
    final_outcome: str,
    hook_wait_ms: int,
    timed_out: bool,
    deadline,
    payload,
    stdin_data: str,
    controls,
    telem_records: list,
) -> None:
    """Append the dispatch record, flush telemetry, run remote lifecycle."""
    from runtime.harness.hook_runner import telemetry as _telemetry

    if not deadline.telemetry_allowed():
        return
    telem_records.append((
        "dispatch",
        {
            "hook_event": event_name,
            "executor": context.executor_family,
            "chain_length": chain_length,
            "decision_outcome": final_outcome,
            "session_id": context.session_id or "",
            "item_id": context.item_id,
            "tool_name": context.tool_name or "",
            "duration_ms": hook_wait_ms,
            "extra": {
                "hook_wait_ms": hook_wait_ms,
                "timed_out": timed_out,
                "total_timeout_ms": deadline.budget_ms,
            },
        },
    ))
    ensure_session = None
    if context.session_id:
        remote = controls is not None and controls.remote
        ensure_session = (  # merged payload: wire extras included
            context.session_id,
            json.dumps(payload) if isinstance(payload, dict) else (stdin_data or ""),
            _str_or(payload.get("transcript_path"), "") or "",
            not remote,
            (context.executor_family or "") if remote else "",
            remote,
            remote and event_name in ("SessionStart", "UserPromptSubmit"),
            # Verified bearer-token actor (server side only): binds
            # harness_sessions.actor_id at relayed ensure-register.
            controls.actor_id if remote else None,
            payload.get("project_id") if isinstance(payload, dict) else None,
        )
    _telemetry.flush_hook_telemetry(
        telem_records, deadline=deadline, ensure_session=ensure_session,
    )
    if controls is not None and controls.remote and context.session_id:
        from runtime.harness.hook_runner.remote_lifecycle import (
            run_remote_session_lifecycle,
        )

        run_remote_session_lifecycle(event_name, context)


__all__ = ["flush_run_tail"]

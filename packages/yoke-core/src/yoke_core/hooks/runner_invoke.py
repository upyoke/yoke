"""Invoke one resolved chain module and report what it decided.

Split out of :mod:`yoke_core.hooks.runner` so the dispatch core holds the
loop, the deadline, and the rendering while this module holds the single
step: run one policy — typed under the watchdog, or as a subprocess — and
return its decision beside the telemetry record the runner batches.
"""

from __future__ import annotations

import time
from typing import Optional

from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.subprocess_policy import run_subprocess_policy
from yoke_core.hooks.typed_dispatch import audit_only_synthetic, dispatch_typed
from yoke_core.hooks.types import HookContext, HookDecision


__all__ = ["invoke_module"]


def dispatch_subprocess(
    module_id: str,
    *,
    context: HookContext,
    stdin_data: str,
    timeout_ms: int,
) -> tuple[Optional[HookDecision], Optional[str], str]:
    """Run a subprocess policy via ``python3 -m <module_id>``."""
    failure, captured = run_subprocess_policy(
        module_id,
        context=context,
        stdin_data=stdin_data,
        timeout_ms=timeout_ms,
    )
    if failure:
        return None, failure, captured
    return audit_only_synthetic(), None, captured


def invoke_module(
    module_id: str,
    *,
    capability: AdapterCapability,
    context: HookContext,
    stdin_data: str,
    timeout_ms: int,
) -> tuple[HookDecision, str, Optional[str], tuple[str, dict]]:
    """Invoke one module; return decision, stdout, failure, telemetry record.

    Telemetry is NOT emitted here. A per-module DB write between guardrail
    evaluations charges its latency against the runner's total deadline and
    can starve the tail of the chain; ``run_event`` flushes the returned
    records as a single batched tail step instead.
    """
    started = time.monotonic()
    if module_id in capability.subprocess_modules:
        decision, failure, captured = dispatch_subprocess(
            module_id,
            context=context,
            stdin_data=stdin_data,
            timeout_ms=timeout_ms,
        )
    else:
        decision, failure = dispatch_typed(
            module_id,
            context=context,
            timeout_ms=timeout_ms,
        )
        captured = ""
    duration_ms = int((time.monotonic() - started) * 1000)
    common = {
        "module": module_id,
        "hook_event": context.event_name,
        "executor": context.executor_family,
        "session_id": context.session_id or "",
        "item_id": context.item_id,
        "tool_name": context.tool_name or "",
        "duration_ms": duration_ms,
    }
    if failure is not None:
        return (
            audit_only_synthetic(),
            captured,
            failure,
            (
                "failed",
                {**common, "failure": failure},
            ),
        )
    assert decision is not None
    return (
        decision,
        captured,
        None,
        (
            "guardrail",
            {**common, "decision_outcome": decision.outcome.value},
        ),
    )

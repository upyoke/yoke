"""PreToolUse hook: flag manual progress polling on long commands.

Detects and flags the anti-pattern where an agent manually polls the output
of a long-running command (duplicate ``Monitor`` arming, background waiters on an existing capture,
short sleeps before reads of registered captures with ``N < 60``, or ``until``/``while``
loops that sleep between ``gh api``/``gh run view`` reads of a CI run).

The canonical pattern agents should use instead: ``Bash(run_in_background=
true)`` with ``Monitor`` tailing the capture file through a line-buffered
filter. When no streaming surface exists, the fallback cadence is
``60s -> 90s -> 120s -> max ~300s``.

Capture reads need no suppression token. ``# lint:no-polling-check``
suppresses the short-sleep rule. It does not unblock a GitHub polling loop: a CI run
Yoke dispatched has a recorded wait whose verdict wakes the session. Monitor
duplicate and background-waiter suppression tokens are audit-only and still
deny.

Typed runner contract:
    ``evaluate(record: HookContext) -> HookDecision``

On a hit the guard always returns a blocking ``DENY`` whose ``message``
carries the plain reason and whose ``audit_fields`` carry the reason, tool
name and audit outcome (``denied`` or ``suppression_attempted``). The hook
runner's mode gate applies ``.yoke/lint-config`` key
``lint_long_command_polling`` (registry default ``deny``); in ``warn`` it
downgrades the decision to a non-blocking warn row.

The CLI ``__main__`` form is preserved for the registered shell hook
entry (``python3 -m yoke_core.domain.lint_long_command_polling``):
``main()`` reads stdin, builds a :class:`HookContext`, calls
``evaluate``, and prints the deny envelope on a deny outcome. Exit code
is always ``0`` (fail-open).

This module owns the hook entry point. Public constants (``CHECK_ID``,
``SUPPRESSION_TOKEN``, plus the cadence thresholds) live in the leaf
``lint_long_command_polling_constants`` sibling and are re-exported here.
The verdict logic lives in ``lint_long_command_polling_evaluate``; pure
command introspection lives in ``lint_long_command_polling_extract``; the
reason formatters live in ``lint_long_command_polling_decide``. Splitting
constants into a leaf module avoids the import cycle that would otherwise
trigger under ``python -m`` invocation.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import sys

from yoke_core.domain.lint_long_command_polling_constants import (  # noqa: F401
    CHECK_ID,
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
    RECENT_EVENT_LOOKBACK_SECONDS,
    SLEEP_CADENCE_FLOOR_SECONDS,
    SUPPRESSION_TOKEN,
)
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_long_command_polling_extract import (  # noqa: F401
    _extract_command,
)
from yoke_core.domain.lint_long_command_polling_evaluate import (
    evaluate_payload,
)
from yoke_core.domain.lint_long_command_polling_monitor_duplicate import (  # noqa: F401
    evaluate_duplicate_monitor,
)
from yoke_core.hooks.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


def _allow_decision() -> HookDecision:
    """Return the canonical no-op decision when the rule does not fire."""
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def evaluate(record: HookContext) -> HookDecision:
    """Run the polling lint against a typed :class:`HookContext`.

    Returns ``NOOP`` when ``evaluate_payload`` surfaces no verdict, else a
    blocking ``DENY`` whose ``audit_fields["audit_outcome"]`` carries the
    verdict's outcome (``denied`` or ``suppression_attempted``).
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    tool_name = record.tool_name or ""
    verdict_result = evaluate_payload(payload, tool_name, record.shell)
    if verdict_result is None:
        return _allow_decision()

    reason, context = verdict_result
    reason = attach_check_id(reason, check_id="lint-long-command-polling")
    outcome_label = (
        context.get("outcome", "denied") if isinstance(context, dict) else "denied"
    )
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={
            "reason": reason,
            "tool_name": tool_name or "Bash",
            "audit_outcome": outcome_label,
        },
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry.

    The CLI entry point still receives Claude PreToolUse JSON on stdin.
    The runtime hook runner normally builds the context, but when the
    Claude shell hook invokes this module directly we need to construct
    one ourselves so ``evaluate`` sees the same shape it would in-runner.
    """
    command_body = _extract_command(payload) or None
    tool_name = payload.get("tool_name")
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=command_body,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
        item_id=None,
        now=None,
    )


def main() -> int:
    """CLI entry: read stdin, evaluate, print deny envelope when denied."""
    try:
        stdin_data = sys.stdin.read() or ""
    except Exception:
        return 0
    try:
        payload = json.loads(stdin_data)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    decision = evaluate(_build_context_from_payload(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

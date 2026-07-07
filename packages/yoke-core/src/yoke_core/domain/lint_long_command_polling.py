"""PreToolUse hook: flag manual progress polling on long commands.

Detects and flags the anti-pattern where an agent manually polls the output
of a long-running command (repeated same-capture ``tail``/``head`` peeks,
duplicate ``Monitor`` arming, background waiters on an existing capture, or
short ``sleep N && tail`` idioms with ``N < 60``).

The canonical pattern agents should use instead: ``Bash(run_in_background=
true)`` with ``Monitor`` tailing the capture file through a line-buffered
filter. When no streaming surface exists, the fallback cadence is
``60s -> 90s -> 120s -> max ~300s``.

Bypass: add ``# lint:no-polling-check`` to a legitimate post-capture
inspection command. Monitor duplicate and background-waiter suppression tokens
are audit-only and still deny in ``deny`` mode.

Modes (from machine config key ``lint_polling_mode``):
- ``warn`` (default): emits a ``HarnessToolCallDenied`` audit event with
  ``[mode=warn]`` in the reason but does NOT block the tool call.
- ``deny``: emits the audit event and blocks via ``hookSpecificOutput``
  ``permissionDecision=deny``.

Typed runner contract:
    ``evaluate(record: HookContext) -> HookDecision``

Behavior is byte-equivalent to the legacy stdin-driven hook. The
decision carries the deny-envelope JSON in ``message`` for ``deny``
outcomes; ``block=True`` is set on deny so the renderer (and any
harness-specific consumer) sees the blocking semantic explicitly.
Audit events still fire from inside ``evaluate`` so warn-mode and
audit-evidence semantics are preserved.

The CLI ``__main__`` form is preserved for the registered shell hook
entry (``python3 -m yoke_core.domain.lint_long_command_polling``):
``main()`` reads stdin, builds a :class:`HookContext`, calls
``evaluate``, and prints the deny envelope on a deny outcome. Exit code
is always ``0`` (fail-open).

This module owns the hook entry point. Public constants
(``CONFIG_KEY_MODE``, ``DEFAULT_MODE``, ``VALID_MODES``, ``CHECK_ID``,
``HOOK_NAME``, ``SUPPRESSION_TOKEN``, plus the cadence / window
thresholds) live in the leaf ``lint_long_command_polling_constants``
sibling and are re-exported here. The
machine-config reader lives in ``lint_long_command_polling_config`` and
is also re-exported. The verdict logic lives in
``lint_long_command_polling_evaluate``; pure command introspection lives
in ``lint_long_command_polling_extract``; the JSON-envelope and
audit-event helpers live in ``lint_long_command_polling_decide``.
Splitting constants and config into leaf modules avoids the import cycle
that would otherwise trigger under ``python -m`` invocation.
"""

from __future__ import annotations

import json
import sys

from yoke_core.domain.lint_long_command_polling_constants import (
    CHECK_ID,
    CONFIG_KEY_MODE,
    DEFAULT_MODE,
    HOOK_NAME,
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
    MTIME_ACTIVE_THRESHOLD_SECONDS,
    PEEK_WINDOW_TURNS,
    RECENT_EVENT_LOOKBACK_SECONDS,
    SLEEP_CADENCE_FLOOR_SECONDS,
    SUPPRESSION_TOKEN,
    VALID_MODES,
)
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_long_command_polling_config import (
    _read_lint_mode,
)
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_command,
    _extract_tool_name,
)
from yoke_core.domain.lint_long_command_polling_decide import (
    _build_deny_response,
    _emit_audit_event,
)
from yoke_core.domain.lint_long_command_polling_evaluate import (
    evaluate_payload,
)
from yoke_core.domain.lint_long_command_polling_monitor_duplicate import (
    evaluate_duplicate_monitor,
)
from runtime.harness.hook_runner.types import (
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

    - Returns ``HookDecision(outcome=NOOP)`` when ``evaluate_payload``
      surfaces no verdict (no polling anti-pattern, suppression token
      honored, etc.).
    - When a verdict fires, the audit event still emits via
      :func:`_emit_audit_event` (preserving warn-mode audit-only
      behavior and ``suppression_attempted`` outcome stamping).
    - In ``warn`` mode the decision is ``WARN`` with no ``block`` and no
      message; the legacy stdout was empty so the renderer keeps stdout
      empty too.
    - In ``deny`` mode the decision is ``DENY`` with ``block=True`` and
      ``message`` carrying the JSON-encoded ``hookSpecificOutput``
      envelope the legacy entry printed verbatim. The
      ``audit_fields`` dict carries the structured reason / mode /
      outcome for telemetry consumers.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict_result = evaluate_payload(payload)
    if verdict_result is None:
        return _allow_decision()

    mode, reason, context = verdict_result
    reason = append_field_note_footer(reason, rule_id="lint-long-command-polling")
    tool_name = _extract_tool_name(payload) or "Bash"
    outcome_label = (
        context.get("outcome", "denied")
        if isinstance(context, dict)
        else "denied"
    )
    _emit_audit_event(
        payload, tool_name, reason, mode, context, outcome=outcome_label,
    )

    audit_fields = {
        "mode": mode,
        "reason": reason,
        "tool_name": tool_name,
        "audit_outcome": outcome_label,
    }
    if mode == "deny":
        deny_envelope = json.dumps(_build_deny_response(reason))
        return HookDecision(
            outcome=Outcome.DENY,
            message=deny_envelope,
            audit_fields=audit_fields,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(
        outcome=Outcome.WARN,
        message="",
        audit_fields=audit_fields,
        block=False,
        next=Next.CONTINUE,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    """Build a minimal :class:`HookContext` for the legacy stdin entry.

    The CLI entry point still receives Claude PreToolUse JSON on stdin.
    The runtime hook runner normally builds the context, but when the
    Claude shell hook invokes this module directly we need to construct
    one ourselves so ``evaluate`` sees the same shape it would in-runner.
    """
    tool_input = payload.get("tool_input")
    command_body = None
    if isinstance(tool_input, dict):
        raw = tool_input.get("command")
        if isinstance(raw, str):
            command_body = raw
    tool_name = payload.get("tool_name")
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) else None,
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
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

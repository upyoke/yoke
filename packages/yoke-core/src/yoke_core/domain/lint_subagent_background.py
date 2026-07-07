"""PreToolUse hook: deny subagent attempts to run background watcher flows.

Yoke subagents (the engineer/tester/architect/boss/simulator agents
dispatched via the Claude ``Agent`` tool) run as *atomic turns*: the
harness fires ``SubagentStop`` at end-of-turn, and any ``Monitor`` wake
that fires after the turn ends has nowhere to deliver. The result is a
deadlock — the subagent suspends mid-flight and the parent dispatch
waits for a wake the orchestrator was never told to send. Operationally
this also leaves orphan watcher subprocesses around ``yoke.db``.

This lint blocks the unsafe shapes in subagent context:

- ``Bash(run_in_background=true)`` — the long-command background pattern.
- ``Monitor`` — wake-as-turn primitive the subagent cannot drive.
- ``ScheduleWakeup`` / ``TaskOutput`` — same wake-loss concern.
- Watcher wrappers (``watch_pytest``, ``watch_merge``, ``watch_doctor``,
  ``watch_tail``) when explicitly backgrounded.

Main-session usage of every one of these surfaces remains valid. The
canonical long-command shape for main sessions is the
``Bash(run_in_background=true)`` + ``Monitor`` pair documented in
``runtime/harness/claude/rules/session.md``.

Subagent context detection
--------------------------

Yoke's :mod:`yoke_core.domain.agent_stop` docstring records a prior
incident where the ``(parent session_id, CLAUDE_PROJECT_DIR)`` heuristic
failed for every real-world subagent dispatch — subagents inherit the
parent's ``CLAUDE_PROJECT_DIR``. The implementation here follows the
same lesson: rely on a structural signal authored by the subagent's
own hook configuration, not on payload guesswork.

The structural signals (in order):

1. ``--agent-type <name>`` CLI flag passed by the subagent's hook
   command line.
2. ``YOKE_HOOK_AGENT_TYPE`` environment variable.
3. ``agent_type`` field on the PreToolUse payload (forward-compat for
   future Claude SDK releases that surface one).

When no signal is present the lint **fails open** (allows the call, no
audit event). Until each subagent JSON adapter is updated to pass one of
those signals the deny path is not yet reachable from a live subagent;
that adapter wiring is the documented follow-up.

Modes (from machine config key ``lint_subagent_background_mode``):

- ``warn`` (default): emit ``HarnessToolCallDenied`` audit event but do
  NOT block.
- ``deny``: emit the audit event AND block via ``hookSpecificOutput``.

Suppression: ``# lint:no-subagent-background-check`` on the Bash command
body or in the ``reason`` of a ``ScheduleWakeup`` payload. The token is
recorded as audit evidence (``outcome=suppression_attempted``) but does
NOT unblock the rule.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Optional

# Strips fd-duplication patterns (`2>&1`, `>&2`, `<&3`, etc.) and the `&&`
# logical-AND operator so the residual `&` is the real backgrounding token.
_FD_DUP_PATTERN = re.compile(r"\d*[<>]>?&\d+")


def _has_real_backgrounding_amp(command: str) -> bool:
    """True when ``&`` appears as a backgrounding operator (not ``2>&1`` / ``&&``)."""
    if not command or "&" not in command:
        return False
    stripped = _FD_DUP_PATTERN.sub("", command).replace("&&", "")
    return "&" in stripped

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_subagent_background_constants import (
    AGENT_TYPE_ENV_VAR,
    CONFIG_KEY_MODE,
    DEFAULT_MODE,
    SUPPRESSION_TOKEN,
    VALID_MODES,
    WAKE_LOSS_TOOLS,
    WATCHER_MODULE_NAMES,
)
from yoke_core.domain.lint_subagent_background_decide import (
    build_deny_response,
    emit_audit_event,
    format_reason,
)
from runtime.harness.hook_runner.types import (
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


# Re-export public constants so callers can import them from this module
# regardless of which sibling defined them (matches polling-lint pattern).
__all__ = [
    "AGENT_TYPE_ENV_VAR",
    "CONFIG_KEY_MODE",
    "DEFAULT_MODE",
    "SUPPRESSION_TOKEN",
    "VALID_MODES",
    "evaluate",
    "evaluate_payload",
    "main",
]


def _read_lint_mode(payload: object | None = None) -> str:
    """Resolve enforcement mode from the single lint_config registry.

    Sourced from ``.yoke/lint-config`` via ``lint_config``.
    """
    try:
        from yoke_core.domain import lint_config
    except Exception:
        return DEFAULT_MODE
    return lint_config.resolve_mode_for_payload("lint_subagent_background", payload)


def _agent_type_from_payload(payload: dict) -> Optional[str]:
    value = payload.get("agent_type") if isinstance(payload, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _detect_agent_type(
    payload: dict, cli_agent_type: Optional[str]
) -> Optional[str]:
    if cli_agent_type and cli_agent_type.strip():
        return cli_agent_type.strip()
    env_value = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    if env_value:
        return env_value
    return _agent_type_from_payload(payload)


def _extract_tool_name(payload: dict) -> str:
    name = payload.get("tool_name")
    return name if isinstance(name, str) else ""


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str):
            return command
    return ""


def _extract_run_in_background(payload: dict) -> bool:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("run_in_background")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
    return False


def _command_invokes_watcher(command: str) -> Optional[str]:
    if not command:
        return None
    for name in WATCHER_MODULE_NAMES:
        if name in command:
            return name
    return None


def _has_suppression(payload: dict) -> bool:
    command = _extract_command(payload)
    if SUPPRESSION_TOKEN in command:
        return True
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        reason = tool_input.get("reason")
        if isinstance(reason, str) and SUPPRESSION_TOKEN in reason:
            return True
    return False


def evaluate_payload(
    payload: dict, *, agent_type: Optional[str] = None,
) -> Optional[tuple[str, str, str, str]]:
    """Return ``(mode, reason, tool_name, outcome)`` when the rule fires.

    Returns ``None`` for the fail-open path: not in subagent context, or
    no protected surface invoked.
    """
    if not isinstance(payload, dict):
        return None
    detected = _detect_agent_type(payload, agent_type)
    if not detected:
        return None

    tool_name = _extract_tool_name(payload)
    command = _extract_command(payload)
    run_in_background = _extract_run_in_background(payload)
    watcher = _command_invokes_watcher(command) if tool_name == "Bash" else None
    suppressed = _has_suppression(payload)

    fires = False
    if tool_name in WAKE_LOSS_TOOLS:
        fires = True
    elif tool_name == "Bash":
        if run_in_background:
            fires = True
        elif watcher and (_has_real_backgrounding_amp(command) or "nohup" in command):
            # Foreground watcher wrapper calls are the canonical subagent
            # shape — only deny when the command is explicitly backgrounded.
            fires = True
    if not fires:
        return None

    mode = _read_lint_mode(payload)
    outcome = "suppression_attempted" if suppressed else "denied"
    reason = append_field_note_footer(
        format_reason(
            tool_name=tool_name,
            command=command,
            watcher=watcher,
            run_in_background=run_in_background,
            suppressed=suppressed,
            mode=mode,
        ),
        rule_id="lint-subagent-background",
    )
    return mode, reason, tool_name, outcome


def _allow_decision() -> HookDecision:
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def evaluate(record: HookContext) -> HookDecision:
    """Run the lint against a typed :class:`HookContext`."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return _allow_decision()
    mode, reason, tool_name, outcome = verdict
    emit_audit_event(
        payload, tool_name, reason, mode, outcome,
        command=_extract_command(payload),
    )
    audit_fields = {
        "mode": mode,
        "reason": reason,
        "tool_name": tool_name,
        "audit_outcome": outcome,
    }
    if mode == "deny":
        return HookDecision(
            outcome=Outcome.DENY,
            message=json.dumps(build_deny_response(reason)),
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


def main() -> int:
    """CLI entry: read stdin, evaluate, print deny envelope on deny.

    Accepts ``--agent-type <name>`` so subagent hook configurations can
    explicitly assert the subagent context the lint should treat them
    under (mirrors the ``observe`` pattern).
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.lint_subagent_background",
        description=(
            "Subagent-context PreToolUse lint. Denies background watcher "
            "and wake-loss-prone surfaces when running inside a Yoke "
            "subagent's hook chain. Fails open for main sessions."
        ),
    )
    parser.add_argument(
        "--agent-type",
        default=None,
        help=(
            "Subagent role name. Sets subagent context explicitly when "
            "the payload-side signal is unavailable."
        ),
    )
    args, _unused = parser.parse_known_args()

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

    verdict = evaluate_payload(payload, agent_type=args.agent_type)
    if verdict is None:
        return 0
    mode, reason, tool_name, outcome = verdict
    emit_audit_event(
        payload, tool_name, reason, mode, outcome,
        command=_extract_command(payload),
    )
    if mode == "deny":
        print(json.dumps(build_deny_response(reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

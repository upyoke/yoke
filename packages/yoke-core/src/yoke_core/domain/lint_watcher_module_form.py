"""PreToolUse Bash hook: retire watcher module forms with CLI adapters.

The watcher wrappers still live in ``yoke_core.tools``, but their supported
agent shape is ``yoke watch <kind>``. A bare module invocation depends on the
caller's import path and bypasses the installed CLI's project-environment
binding. This guard keeps the old spelling from returning after the adapter
has shipped.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import shlex
import sys
from typing import Optional, Tuple

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command


CHECK_ID = "lint-watcher-module-form"
SUPPRESSION_TOKEN = "# lint:no-watcher-module-form-check"
_PYTHON_NAMES = {"python", "python3"}


def _legacy_forms(command: str) -> tuple[tuple[str, str], ...]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return ()
    found: list[tuple[str, str]] = []
    for index in range(len(tokens) - 2):
        if os.path.basename(tokens[index]) not in _PYTHON_NAMES:
            continue
        if tokens[index + 1] != "-m":
            continue
        module = tokens[index + 2]
        if module not in WATCH_CLI_TOKENS:
            continue
        form = cli_form(module)
        if form is not None:
            found.append((module, form))
    return tuple(found)


def _format_reason(
    forms: tuple[tuple[str, str], ...],
    suppression_seen: bool,
) -> str:
    old = ", ".join(module for module, _ in forms)
    replacements = "\n".join(
        f"  {old_form}  ->  {cli_form_value}" for old_form, cli_form_value in forms
    )
    body = (
        "BLOCKED: legacy watcher module form is retired.\n\n"
        f"Found: {old}\n\n"
        f"Use the first-class yoke CLI adapter:\n{replacements}"
    )
    if suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence but does NOT unblock this rule."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Return ``(reason, audit_outcome)`` for a legacy watcher form, else None."""
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    forms = _legacy_forms(command)
    if not forms:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(forms, suppression_seen)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason, "audit_outcome": outcome},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: dict) -> HookContext:
    command = _extract_command(payload)
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=command or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "")
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

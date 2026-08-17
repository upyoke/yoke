"""PreToolUse Bash hook: retire watcher module forms with CLI adapters.

The watcher wrappers still live in ``yoke_core.tools``, but their supported
agent shape is ``yoke watch <kind>``. A bare module invocation depends on the
caller's import path and bypasses the installed CLI's project-environment
binding. This guard keeps the old spelling from returning after the adapter
has shipped.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from typing import Optional, Tuple

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


CHECK_ID = "lint-watcher-module-form"
HOOK_NAME = CHECK_ID
SUPPRESSION_TOKEN = "# lint:no-watcher-module-form-check"
_PYTHON_NAMES = {"python", "python3"}


def _extract_command(payload: dict) -> str:
    for key in ("tool_input", "toolInput", "input"):
        value = payload.get(key)
        if isinstance(value, dict):
            for command_key in ("command", "cmd"):
                command = value.get(command_key)
                if isinstance(command, str) and command:
                    return command
    command = payload.get("command")
    return command if isinstance(command, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_watcher_module_form", payload,
    )


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
    forms: tuple[tuple[str, str], ...], suppression_seen: bool, mode: str,
) -> str:
    old = ", ".join(module for module, _ in forms)
    replacements = "\n".join(
        f"  {old_form}  ->  {cli_form_value}"
        for old_form, cli_form_value in forms
    )
    body = (
        "BLOCKED: legacy watcher module form is retired.\n\n"
        f"Found: {old}\n\n"
        "Use the first-class yoke CLI adapter, which resolves the project "
        "environment and keeps the wrapper's help/telemetry contract:\n"
        f"{replacements}\n\n"
        "The module implementation remains package-owned for the adapter and "
        "operator tooling; it is not an agent invocation shape."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence but does NOT unblock this rule."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    forms = _legacy_forms(command)
    if not forms:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(forms, suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else (
        "denied" if mode == "deny" else "warned"
    )
    return mode, reason, outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event

        emit_denial_event(
            hook=HOOK_NAME,
            tool="Bash",
            check_id=CHECK_ID,
            reason=f"[mode={mode}] {reason}" if mode == "warn" else reason,
            session_id=str(payload.get("session_id") or ""),
            tool_use_id=str(payload.get("tool_use_id") or ""),
            turn_id=str(payload.get("turn_id") or payload.get("message_id") or ""),
            command_snippet=_extract_command(payload),
            outcome=outcome,
        )
    except Exception:
        return


def evaluate(record: HookContext) -> HookDecision:
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    command = _extract_command(payload)
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
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
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

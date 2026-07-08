"""PreToolUse Bash hook: block ``fi; rc=$?`` status capture.

In Bash, the status of an ``if`` compound is the status of the branch body
that ran. If no branch body runs, the compound succeeds. A command such as
``if build; then exit 0; fi; rc=$?`` therefore records the ``if`` status, not
the failed ``build`` status. The result is the quietest possible failure mode:
the command can fail twice and the wrapper still exits 0.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional, Tuple

from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.denial_field_note_footer import append_field_note_footer

CHECK_ID = "lint-if-status-capture"
HOOK_NAME = "lint-if-status-capture"
SUPPRESSION_TOKEN = "# lint:no-if-status-capture-check"

_IF_STATUS_CAPTURE_RE = re.compile(
    r"\bfi\b[ \t]*(?:;|&&|\|\||\n)[ \t]*(?P<assignment>[A-Za-z_][A-Za-z0-9_]*=\$\?)",
    re.MULTILINE,
)


def _extract_command(payload: dict) -> str:
    for key in ("tool_input", "toolInput", "input"):
        tool_input = payload.get(key)
        if isinstance(tool_input, dict):
            for command_key in ("command", "cmd"):
                value = tool_input.get(command_key)
                if isinstance(value, str) and value:
                    return value
    value = payload.get("command")
    return value if isinstance(value, str) else ""


def _extract_tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload("lint_if_status_capture", payload)


def _find_if_status_capture(command: str) -> Optional[str]:
    match = _IF_STATUS_CAPTURE_RE.search(command)
    if match is None:
        return None
    return match.group("assignment")


def _format_reason(assignment: str, suppression_seen: bool, mode: str) -> str:
    body = (
        "BLOCKED: Bash command captures `$?` immediately after `fi`.\n\n"
        f"Detected: `{assignment}` after an `if` compound.\n\n"
        "That captures the status of the `if` compound, not necessarily the "
        "command that failed in the condition. When the condition is false and "
        "there is no `else` branch, Bash reports the `if` compound as success, "
        "so a failed command can be recorded as exit 0.\n\n"
        "Safe shape:\n"
        "  if build_image; then\n"
        "    exit 0\n"
        "  else\n"
        "    rc=$?\n"
        "  fi\n\n"
        "If you need an aggregate boolean from the whole conditional, assign an "
        "explicit value inside the branches instead of reading `$?` after `fi`."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    assignment = _find_if_status_capture(command)
    if assignment is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(assignment, suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return mode, reason, outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    try:
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
        pass


def evaluate(record: HookContext) -> HookDecision:
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    mode, reason, outcome = verdict
    _emit_audit_event(payload, reason, mode, outcome)
    audit = {"mode": mode, "reason": reason, "audit_outcome": outcome}
    if mode == "deny":
        envelope = json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            audit_fields=audit,
            block=True,
            next=Next.STOP,
        )
    return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)


def _build_context_from_payload(payload: dict) -> HookContext:
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
        command_body=_extract_command(payload) or None,
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

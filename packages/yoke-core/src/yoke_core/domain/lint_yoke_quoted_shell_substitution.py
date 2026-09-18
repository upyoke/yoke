"""PreToolUse Bash lint: refuse yoke args the shell would substitute."""

from __future__ import annotations

import json
import re
import sys
from typing import Optional, Tuple

from yoke_core.domain.lint_shell_backtick_search import (
    _double_quoted_spans,
    _extract_command,
    _extract_tool_name,
    _has_unescaped_backtick,
    _segment_until_shell_separator,
)
from yoke_core.domain.lint_yoke_quoted_shell_substitution_messages import (
    CHECK_ID,
    HOOK_NAME,
    SUPPRESSION_TOKEN,
    format_reason,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

# Command token is exactly ``yoke`` (optional path prefix), not ``yoke-cli``.
_YOKE_CMD_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:\S*/)?yoke(?=\s|$)"
)
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?\w+")


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(
        "lint_yoke_quoted_shell_substitution", payload,
    )


def _has_unescaped_dollar_paren(span: str) -> bool:
    escaped = False
    index = 0
    while index < len(span):
        char = span[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char == "$" and index + 1 < len(span) and span[index + 1] == "(":
            return True
        index += 1
    return False


def _strip_heredoc(segment: str) -> str:
    match = _HEREDOC_RE.search(segment)
    if match is None:
        return segment
    return segment[: match.start()]


def _yoke_substituted_span(command: str) -> Optional[str]:
    for match in _YOKE_CMD_RE.finditer(command):
        segment = _strip_heredoc(
            _segment_until_shell_separator(command[match.end() :])
        )
        for span in _double_quoted_spans(segment):
            if _has_unescaped_backtick(span) or _has_unescaped_dollar_paren(span):
                return span
    return None


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str, str]]:
    if not isinstance(payload, dict):
        return None
    tool = _extract_tool_name(payload)
    if tool and tool != "Bash":
        return None
    command = _extract_command(payload)
    if not command:
        return None
    span = _yoke_substituted_span(command)
    if span is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = format_reason(span, suppression_seen, mode)
    outcome = "suppression_attempted" if suppression_seen else "denied"
    return mode, reason, outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from yoke_core.hooks.telemetry import emit_denial_event
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

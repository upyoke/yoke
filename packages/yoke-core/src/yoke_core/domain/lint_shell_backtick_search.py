"""PreToolUse Bash hook: refuse backticks in double-quoted search patterns."""

from __future__ import annotations

import json
import re
import sys
from typing import Optional, Tuple

from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.denial_field_note_footer import append_field_note_footer

CHECK_ID = "lint-shell-backtick-search"
HOOK_NAME = "lint-shell-backtick-search"
SUPPRESSION_TOKEN = "# lint:no-backtick-search-check"

_GREP_LIKE_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:\S*/)?(?:rg|grep|egrep|fgrep)\b"
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

    return lint_config.resolve_mode_for_payload(
        "lint_shell_backtick_search", payload,
    )


def _double_quoted_spans(text: str) -> list[str]:
    spans: list[str] = []
    current: list[str] = []
    in_double = False
    escaped = False
    for char in text:
        if escaped:
            if in_double:
                current.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            if in_double:
                spans.append("".join(current))
                current = []
                in_double = False
            else:
                in_double = True
            continue
        if in_double:
            current.append(char)
    return spans


def _has_unescaped_backtick(span: str) -> bool:
    escaped = False
    for char in span:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "`":
            return True
    return False


def _segment_until_shell_separator(text: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and not in_single:
            escaped = True
            index += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if text.startswith("&&", index) or text.startswith("||", index):
                return text[:index]
            if char in ";|":
                return text[:index]
        index += 1
    return text


def _grep_like_backtick_span(command: str) -> Optional[str]:
    for match in _GREP_LIKE_RE.finditer(command):
        rest = command[match.end():]
        segment = _segment_until_shell_separator(rest)
        for span in _double_quoted_spans(segment):
            if _has_unescaped_backtick(span):
                return span
    return None


def _format_reason(span: str, suppression_seen: bool, mode: str) -> str:
    preview = span if len(span) <= 160 else span[:157] + "..."
    body = (
        "BLOCKED: grep/rg search text contains a backtick inside double quotes.\n\n"
        f"Search text: {preview!r}\n\n"
        "Backticks still run command substitution inside double quotes. "
        "Use single quotes for literal Markdown/code searches, or escape each "
        "backtick when command substitution is intentional.\n\n"
        "Examples:\n"
        "  rg '`literal`' docs/\n"
        "  grep -R '`literal`' AGENTS.md docs/\n"
    )
    if mode == "warn":
        body += "\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
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
    span = _grep_like_backtick_span(command)
    if span is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    mode = _read_mode(payload)
    reason = _format_reason(span, suppression_seen, mode)
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

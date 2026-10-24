"""PreToolUse Bash hook: refuse backticks in double-quoted search patterns."""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import sys
from typing import Optional, Tuple

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.shell_expansion_scan import double_quoted_spans
from yoke_contracts.hook_runner.shell_parse import ShellParse
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-shell-backtick-search"
SUPPRESSION_TOKEN = "# lint:no-backtick-search-check"

_SEARCH_PROGRAMS = frozenset({"rg", "grep", "egrep", "fgrep"})


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


def _grep_like_backtick_span(shell: ShellParse) -> Optional[str]:
    for segment in shell.segments:
        if segment.program not in _SEARCH_PROGRAMS:
            continue
        for span in double_quoted_spans(segment.text):
            if _has_unescaped_backtick(span):
                return span
    return None


def _format_reason(span: str, suppression_seen: bool) -> str:
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
    if suppression_seen:
        body += (
            f"\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict, shell: ShellParse) -> Optional[Tuple[str, str]]:
    if not isinstance(payload, dict):
        return None
    command = shell.command
    if not command:
        return None
    span = _grep_like_backtick_span(shell)
    if span is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(span, suppression_seen)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload, record.shell)
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
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
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
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

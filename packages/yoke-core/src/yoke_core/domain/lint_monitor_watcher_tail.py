"""Require sentinel-aware Monitor tails for watcher captures.

Watcher progress and raw captures carry an exit sentinel understood by
``yoke watch tail``. A bare ``tail -f`` or ``tail -F`` ignores that sentinel
and leaves its Monitor subscription alive after the watched command exits.
This PreToolUse guard blocks only that exact shape on watcher-owned captures;
ordinary log tails remain available.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import os
import shlex
import sys
from pathlib import PurePath
from typing import Optional

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell
from yoke_core.domain.lint_long_command_polling_extract import _extract_command


CHECK_ID = "lint-monitor-watcher-tail"
SUPPRESSION_TOKEN = "# lint:no-monitor-watcher-tail-check"
_FOLLOW_FLAGS = frozenset({"-f", "-F"})


def _watcher_capture_path(command: str | ShellParse) -> Optional[str]:
    """Return the path from a bare watcher ``tail -f`` shape."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    if len(parsed.segments) != 1 or parsed.unparsed:
        return None
    tokens = list(parsed.segments[0].tokens)
    suppression = SUPPRESSION_TOKEN.split()
    for index in range(len(tokens)):
        if tokens[index : index + len(suppression)] == suppression:
            tokens = tokens[:index]
            break
    if len(tokens) != 3:
        return None
    executable, flag, path = tokens
    if os.path.basename(executable) != "tail" or flag not in _FOLLOW_FLAGS:
        return None

    selected = PurePath(path)
    if "watcher-captures" not in selected.parts:
        return None
    name = selected.name
    if not name.startswith("yoke-") or not name.endswith(".log"):
        return None
    if ".progress." not in name and ".raw." not in name:
        return None
    return path


def _format_reason(path: str, suppression_seen: bool) -> str:
    replacement = f"yoke watch tail {shlex.quote(path)}"
    body = (
        "BLOCKED: bare tail follow does not exit when a watcher command "
        "writes its completion sentinel.\n\n"
        "Use the sentinel-aware Monitor command minted by the watcher:\n"
        f"  {replacement}\n\n"
        "Bare tail -f/-F remains valid for non-watcher logs."
    )
    if suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence but does NOT unblock this rule."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(
    payload: dict, shell: Optional[ShellParse] = None
) -> Optional[tuple[str, str]]:
    """Return ``(reason, audit_outcome)`` for a bare watcher tail, else None.

    *shell* is the hook's shared parse of the payload's command.
    """
    if not isinstance(payload, dict):
        return None
    parsed = shell if shell is not None else parse_shell(_extract_command(payload))
    path = _watcher_capture_path(parsed)
    if path is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in parsed.command
    reason = _format_reason(path, suppression_seen)
    return reason, "suppression_attempted" if suppression_seen else "denied"


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name != "Monitor":
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


def _context(payload: dict) -> HookContext:
    command = _extract_command(payload)
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=command or None,
        cwd=payload.get("cwd") if isinstance(payload.get("cwd"), str) else None,
        session_id=(
            payload.get("session_id")
            if isinstance(payload.get("session_id"), str)
            else None
        ),
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    decision = evaluate(_context(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Require sentinel-aware Monitor tails for watcher captures.

Watcher progress and raw captures carry an exit sentinel understood by
``yoke watch tail``. A bare ``tail -f`` or ``tail -F`` ignores that sentinel
and leaves its Monitor subscription alive after the watched command exits.
This PreToolUse guard blocks only that exact shape on watcher-owned captures;
ordinary log tails remain available.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import PurePath
from typing import Optional

from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_long_command_polling_extract import (
    _extract_command,
    _extract_tool_name,
)


CHECK_ID = "lint-monitor-watcher-tail"
HOOK_NAME = CHECK_ID
GUARD_KEY = "lint_monitor_watcher_tail"
SUPPRESSION_TOKEN = "# lint:no-monitor-watcher-tail-check"
_FOLLOW_FLAGS = frozenset({"-f", "-F"})


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config

    return lint_config.resolve_mode_for_payload(GUARD_KEY, payload)


def _watcher_capture_path(command: str) -> Optional[str]:
    """Return the path from a bare watcher ``tail -f`` shape."""
    candidate = command.partition(SUPPRESSION_TOKEN)[0].strip()
    try:
        tokens = shlex.split(candidate, posix=True)
    except ValueError:
        return None
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


def _format_reason(path: str, suppression_seen: bool, mode: str) -> str:
    replacement = f"yoke watch tail {shlex.quote(path)}"
    body = (
        "BLOCKED: bare tail follow does not exit when a watcher command "
        "writes its completion sentinel.\n\n"
        "Use the sentinel-aware Monitor command minted by the watcher:\n"
        f"  {replacement}\n\n"
        "Bare tail -f/-F remains valid for non-watcher logs."
    )
    if mode == "warn":
        body += "\n\n[mode=warn] this hook would block in deny mode."
    elif suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence but does NOT unblock this rule."
        )
    return append_field_note_footer(body, rule_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[tuple[str, str, str]]:
    if not isinstance(payload, dict) or _extract_tool_name(payload) != "Monitor":
        return None
    command = _extract_command(payload)
    path = _watcher_capture_path(command)
    if path is None:
        return None
    mode = _read_mode(payload)
    suppression_seen = SUPPRESSION_TOKEN in command
    outcome = "suppression_attempted" if suppression_seen else (
        "denied" if mode == "deny" else "warned"
    )
    return mode, _format_reason(path, suppression_seen, mode), outcome


def _emit_audit_event(payload: dict, reason: str, mode: str, outcome: str) -> None:
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event

        emit_denial_event(
            hook=HOOK_NAME,
            tool="Monitor",
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


def _context(payload: dict) -> HookContext:
    command = _extract_command(payload)
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=_extract_tool_name(payload) or None,
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
        print(decision.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())

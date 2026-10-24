"""PreToolUse Bash guard for operator-machine privacy boundaries.

The classifier names what a command touches; the severity map in
:mod:`local_privacy_messages` decides what that means live. Personal-folder
reads and GUI automation are the harness prompt's and the operating system's
call, so this guard stays out of them entirely. Broad home discovery gets one
advisory line. Only the system privacy database still denies; the shared
mode gate applies the operator's configured warn/deny policy to that denial.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
from pathlib import Path
import sys
from typing import Optional, Tuple

from yoke_contracts.hook_runner.local_privacy_guard import classify_shell_command
from yoke_contracts.hook_runner.local_privacy_messages import (
    LIVE_ADVISORY,
    LIVE_DENY,
)
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_core.domain.lint_command_extract import extract_command as _extract_command


CHECK_ID = "lint-local-privacy"


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    """Return ``(reason, audit_outcome)`` — ``denied`` or ``advisory`` — or None."""
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    finding = classify_shell_command(
        command,
        home=Path.home(),
        cwd=(payload.get("cwd") if isinstance(payload.get("cwd"), str) else Path.cwd()),
    )
    if finding is None:
        return None
    severity = finding.live_severity
    if severity not in (LIVE_DENY, LIVE_ADVISORY):
        return None
    reason = attach_check_id(finding.reason(), check_id=CHECK_ID)
    # An advisory is the guard's own non-blocking note under every policy.
    return reason, "advisory" if severity == LIVE_ADVISORY else "denied"


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason, outcome = verdict
    audit = {"reason": reason, "audit_outcome": outcome}
    if outcome == "advisory":
        audit["additionalContext"] = reason
        return HookDecision(outcome=Outcome.WARN, message="", audit_fields=audit)
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields=audit,
        block=True,
        next=Next.STOP,
    )


def _context(payload: dict) -> HookContext:
    tool_name = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool_name if isinstance(tool_name, str) and tool_name else None,
        command_body=_extract_command(payload) or None,
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

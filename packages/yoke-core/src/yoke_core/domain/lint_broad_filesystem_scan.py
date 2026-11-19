"""PreToolUse Bash guard: refuse whole-disk find/fd/bfs/locate scans.

The classifier and refusal text live in
:mod:`yoke_contracts.hook_runner.broad_filesystem_scan`, shared with the
client-local guard, so both hook paths decide identically.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Optional

from yoke_contracts.hook_runner.broad_filesystem_scan import (
    CHECK_ID,
    broad_scan_reason,
    find_broad_scan,
)
from yoke_core.domain.lint_command_extract import extract_command as _extract_command
from yoke_core.hooks.decision_render import render_codex_decision
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


def evaluate_payload(record: HookContext) -> Optional[str]:
    """Return the refusal text when the command would walk the whole disk."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    cwd = payload.get("cwd")
    scan = find_broad_scan(
        record.shell,
        cwd=cwd if isinstance(cwd, str) else record.cwd,
        home=str(Path.home()),
    )
    return broad_scan_reason(scan) if scan is not None else None


def evaluate(record: HookContext) -> HookDecision:
    if record.tool_name and record.tool_name != "Bash":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = evaluate_payload(record)
    if reason is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    return HookDecision(
        outcome=Outcome.DENY,
        message=reason,
        audit_fields={"reason": reason, "audit_outcome": "denied", "check_id": CHECK_ID},
        block=True,
        next=Next.STOP,
    )


def _context(payload: dict) -> HookContext:
    tool_name = payload.get("tool_name")
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")
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
    decision = evaluate(_context(payload))
    if decision.outcome is Outcome.DENY and decision.message:
        print(render_codex_decision([decision], "PreToolUse")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

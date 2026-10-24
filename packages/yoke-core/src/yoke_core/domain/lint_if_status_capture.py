"""PreToolUse Bash hook: block ``fi; rc=$?`` status capture.

In Bash, the status of an ``if`` compound is the status of the branch body
that ran. If no branch body runs, the compound succeeds. A command such as
``if build; then exit 0; fi; rc=$?`` therefore records the ``if`` status, not
the failed ``build`` status. The result is the quietest possible failure mode:
the command can fail twice and the wrapper still exits 0.
"""

from __future__ import annotations

from yoke_core.hooks.decision_render import render_codex_decision

import json
import re
import sys
from typing import Optional, Tuple

from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_command_extract import extract_command as _extract_command

CHECK_ID = "lint-if-status-capture"
SUPPRESSION_TOKEN = "# lint:no-if-status-capture-check"

_IF_STATUS_CAPTURE_RE = re.compile(
    r"\bfi\b[ \t]*(?:;|&&|\|\||\n)[ \t]*(?P<assignment>[A-Za-z_][A-Za-z0-9_]*=\$\?)",
    re.MULTILINE,
)


def _find_if_status_capture(command: str) -> Optional[str]:
    match = _IF_STATUS_CAPTURE_RE.search(command)
    if match is None:
        return None
    return match.group("assignment")


def _format_reason(assignment: str, suppression_seen: bool) -> str:
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
    if suppression_seen:
        body += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` is recorded as audit "
            "evidence (outcome=suppression_attempted) but does NOT unblock."
        )
    return attach_check_id(body, check_id=CHECK_ID)


def evaluate_payload(payload: dict) -> Optional[Tuple[str, str]]:
    if not isinstance(payload, dict):
        return None
    command = _extract_command(payload)
    if not command:
        return None
    assignment = _find_if_status_capture(command)
    if assignment is None:
        return None
    suppression_seen = SUPPRESSION_TOKEN in command
    reason = _format_reason(assignment, suppression_seen)
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

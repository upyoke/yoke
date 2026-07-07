"""Neutral implementation for the Bash DB-command policy hook.

Every denial still emits the legacy stable ``lint-sqlite-cmd``
telemetry/check id. That id is an audit-history anchor, not evidence that
Yoke still runs a SQLite control-plane backend.

Typed entry: ``evaluate(record: HookContext) -> HookDecision`` wraps
:func:`yoke_core.domain.lint_db_runner.run_hook`. Rule definitions live in
:mod:`yoke_core.domain.lint_db_rules` (``HOOK_POLICY_SOURCE``).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any, Dict, Tuple

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_db_rules import HOOK_POLICY_SOURCE
from yoke_core.domain.lint_db_runner import run_hook
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome

LEGACY_HOOK_ID = "lint-sqlite-cmd"

__all__ = [
    "HOOK_POLICY_SOURCE",
    "LEGACY_HOOK_ID",
    "evaluate",
    "main",
    "run_hook",
]


def _resolve_db_fallback() -> str:
    """Return a legacy DB token when one is safely available.

    The programmatic :func:`run_hook(payload, yoke_db=...)` entry point
    continues to honor explicitly injected paths for tests and Codex. The
    fallback delegates to the retired resolver guard and degrades to ``""``
    when Postgres authority refuses path-based resolution; lint hooks must
    remain fail-open.
    """
    try:
        from yoke_core.domain.db_helpers import resolve_db_path

        return resolve_db_path() or ""
    except Exception:
        return ""


def _parse_payload(raw: str) -> Dict[str, Any]:
    """Parse the PreToolUse payload; return ``{}`` on any failure."""
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _extract_command(payload: Dict[str, Any]) -> str:
    """Extract the Bash command string from various payload shapes."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = payload.get("toolInput")
    if not isinstance(tool_input, dict):
        tool_input = payload.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    command = tool_input.get("command")
    if isinstance(command, str) and command:
        return command
    cmd = tool_input.get("cmd")
    if isinstance(cmd, str) and cmd:
        return cmd
    top_cmd = payload.get("command")
    if isinstance(top_cmd, str) and top_cmd:
        return top_cmd
    return ""


def _deny_reason_from_output(output: str) -> Tuple[bool, str]:
    """Return ``(is_deny, reason)`` for a hook output string."""
    if not output:
        return False, ""
    try:
        data = json.loads(output)
    except Exception:
        return False, ""
    if not isinstance(data, dict):
        return False, ""
    hook_specific = data.get("hookSpecificOutput")
    if not isinstance(hook_specific, dict):
        return False, ""
    if hook_specific.get("permissionDecision") != "deny":
        return False, ""
    reason = hook_specific.get("permissionDecisionReason") or ""
    return True, str(reason)


def _emit_legacy_denial(payload: Dict[str, Any], reason: str) -> None:
    """Emit HarnessToolCallDenied for the stable legacy denial id; fail-open."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    command_snippet = _extract_command(payload)
    try:
        emit_denial_event(
            hook=LEGACY_HOOK_ID,
            tool="Bash",
            check_id=LEGACY_HOOK_ID,
            reason=reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            command_snippet=command_snippet,
        )
    except Exception:
        pass


def evaluate(
    record: HookContext,
    *,
    run_hook_func: Callable[[str, str], str] | None = None,
    db_fallback_resolver: Callable[[], str] | None = None,
) -> HookDecision:
    """Typed entry. Wraps :func:`run_hook` with HookContext / HookDecision."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    raw = json.dumps(payload)
    runner = run_hook_func or run_hook
    fallback = db_fallback_resolver or _resolve_db_fallback
    yoke_db = os.environ.get("YOKE_DB", "") or fallback()
    output = runner(raw, yoke_db)
    if not output:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    is_deny, reason = _deny_reason_from_output(output)
    if not is_deny:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    reason = append_field_note_footer(reason, rule_id=LEGACY_HOOK_ID)
    output = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }})
    _emit_legacy_denial(payload, reason)
    return HookDecision(
        outcome=Outcome.DENY,
        message=output,
        audit_fields={"reason": reason},
        block=True,
        next=Next.STOP,
    )


def _build_context_from_payload(payload: Dict[str, Any]) -> HookContext:
    cwd = payload.get("cwd")
    sid = payload.get("session_id")
    tool = payload.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool if isinstance(tool, str) else None,
        command_body=_extract_command(payload) or None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )


def main(
    *,
    run_hook_func: Callable[[str, str], str] | None = None,
    db_fallback_resolver: Callable[[], str] | None = None,
) -> int:
    """CLI entry: stdin -> evaluate -> emit deny envelope when denied."""
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    payload = _parse_payload(raw)
    decision = evaluate(
        _build_context_from_payload(payload),
        run_hook_func=run_hook_func,
        db_fallback_resolver=db_fallback_resolver,
    )
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

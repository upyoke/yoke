"""Reason formatter, deny envelope, and audit emission for the subagent-background lint.

Split from :mod:`yoke_core.domain.lint_subagent_background` so the
entry-point stays under the 350-line file cap (mirroring the
``lint_long_command_polling_decide`` split). Pure command/payload
introspection helpers live alongside the entry point; this module owns
the rendered-output side of the lint.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.lint_subagent_background_constants import (
    CHECK_ID,
    HOOK_NAME,
    SUPPRESSION_TOKEN,
)


__all__ = [
    "build_deny_response",
    "format_reason",
    "emit_audit_event",
]


def build_deny_response(reason: str) -> dict:
    """Return the Claude-shaped hookSpecificOutput deny envelope."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def format_reason(
    *,
    tool_name: str,
    command: str,
    watcher: Optional[str],
    run_in_background: bool,
    suppressed: bool,
    mode: str,
) -> str:
    """Render the operator-facing block that the deny envelope carries.

    The text is intentionally long so a single deny event is enough to
    explain what fired, the architectural reason, the canonical
    workaround, and the suppression-token semantics.
    """
    verb = "DENIED" if mode == "deny" else "SUBAGENT BACKGROUND PATTERN"
    if tool_name == "Monitor":
        body = (
            "Monitor is the wake-as-turn primitive — subagent dispatched "
            "turns end before a wake can land, so the watcher leaks and "
            "the parent dispatch deadlocks waiting for a notification the "
            "orchestrator was never told to send."
        )
    elif tool_name == "ScheduleWakeup":
        body = (
            "ScheduleWakeup against a subagent turn cannot deliver — the "
            "turn ends at end-of-tool-sequence and the scheduled wake has "
            "nowhere to land. Subagents are atomic by design."
        )
    elif tool_name == "TaskOutput":
        body = (
            "TaskOutput in a subagent turn cannot poll a parallel "
            "background task — the parent orchestrator owns the "
            "background pair, not the subagent."
        )
    elif watcher:
        body = (
            f"Watcher wrapper `{watcher}` was invoked in a subagent "
            "context. Subagents must run long commands FOREGROUND inside "
            "a single Bash tool call so the wrapper exits before the "
            "turn does — never paired with Monitor or run_in_background."
        )
    elif run_in_background:
        body = (
            "Bash(run_in_background=true) in a subagent turn leaves a "
            "background process the subagent cannot drive — Monitor wakes "
            "after the turn ends have nowhere to deliver."
        )
    else:
        body = (
            "Subagent dispatched turns must not arm background watcher "
            "flows. Run long commands foreground inside a single tool "
            "call sequence."
        )

    guidance = (
        "\n\nCanonical subagent long-command shape:\n"
        "  python3 -m yoke_core.tools.watch_pytest -- <pytest args>\n"
        "  python3 -m yoke_core.tools.watch_merge done-transition <args>\n"
        "Each blocks foreground in one Bash call, writes raw + filtered "
        "captures under the helper-resolved scratch root "
        "(`project_scratch_dir.watcher_capture_path(...)`), and exits "
        "before the turn does. The wrapper prints the raw-capture path "
        "on exit — inspect with `tail -80 <raw-capture>` after completion.\n\n"
        "If the turn budget cannot accommodate the foreground run, ask "
        "the parent orchestrator for a tighter dispatch scope. Growing "
        "the budget to fit a self-armed background pattern is not a "
        "workaround. See `runtime/harness/claude/rules/session.md` "
        "`## Tool Constraints` for the full rule."
    )
    text = f"{verb}: " + body + guidance
    if suppressed:
        text += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` was detected "
            "and recorded for audit, but it does NOT unblock this rule. "
            "Run the command foreground instead."
        )
    return text


def _safe_str(value, default: str = "") -> str:
    return value if isinstance(value, str) else default


def emit_audit_event(
    payload: dict,
    tool_name: str,
    reason: str,
    mode: str,
    outcome: str,
    *,
    command: str = "",
) -> None:
    """Emit ``HarnessToolCallDenied`` with mode/outcome annotated reason."""
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return
    session_id = _safe_str(payload.get("session_id"))
    tool_use_id = _safe_str(payload.get("tool_use_id"))
    turn_id = _safe_str(payload.get("turn_id") or payload.get("message_id"))
    command_snippet = (command or "")[:256]
    annotated = f"[mode={mode}] {reason}"
    if outcome and outcome != "denied":
        annotated = f"[mode={mode}][outcome={outcome}] {reason}"
    try:
        emit_denial_event(
            hook=HOOK_NAME,
            tool=tool_name or "",
            check_id=CHECK_ID,
            reason=annotated,
            session_id=session_id,
            tool_use_id=tool_use_id,
            turn_id=turn_id,
            command_snippet=command_snippet,
            outcome=outcome or "denied",
        )
    except Exception:
        pass

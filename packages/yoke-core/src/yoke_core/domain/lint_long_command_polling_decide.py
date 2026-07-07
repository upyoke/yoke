"""Output-side helpers for the polling lint: reasons, context, audit, deny.

Sibling of ``lint_long_command_polling`` (the hook entry point) and
``lint_long_command_polling_evaluate`` (the verdict logic). This module
isolates everything that builds output:

- ``_format_peek_reason`` / ``_format_sleep_reason`` /
  ``_format_monitor_duplicate_reason`` — operator-facing reason text rendered with
  the verdict (``DENIED`` vs ``POLLING ANTI-PATTERN``).
- ``_build_context`` — the structured context dict captured into the
  audit event.
- ``_build_deny_response`` — the Claude PreToolUse JSON envelope used to
  signal ``permissionDecision=deny``.
- ``_emit_audit_event`` — the ``HarnessToolCallDenied`` audit event with
  mode-aware (``[mode=warn]`` vs ``[mode=deny]``) reason annotation.

The formatters are pulled by ``evaluate_payload`` so the verdict tuple
already carries the rendered reason. The remaining helpers are imported
by the entry-point ``run()``.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.lint_long_command_polling_constants import (
    CHECK_ID,
    HOOK_NAME,
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
    PEEK_WINDOW_TURNS,
    SUPPRESSION_TOKEN,
)
from yoke_core.domain.lint_long_command_polling_extract import _extract_command


def _raw_capture_hint(progress_capture: str) -> str:
    """Best-effort raw-capture path for the duplicate-Monitor reason text.

    Yoke's watcher wrappers write a paired raw + progress capture (see
    ``yoke_core.tools._watch_runner``). The convention is
    ``<base>.raw.<suffix>`` next to ``<base>.progress.<suffix>``; the
    reason text routes the agent to the raw capture for post-completion
    inspection. When the progress path doesn't carry the ``.progress.``
    marker, fall back to the path itself so the hint stays legible.
    """
    if ".progress." in progress_capture:
        return progress_capture.replace(".progress.", ".raw.", 1)
    return progress_capture


def _format_peek_reason(
    capture_file: str,
    prior_peeks: int,
    mode: str,
) -> str:
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    return (
        f"{verb}: Manual progress peek on long command.\n\n"
        f"Target: {capture_file}\n"
        f"Prior peeks in last {PEEK_WINDOW_TURNS}-turn window: {prior_peeks}\n\n"
        "The canonical pattern for monitoring long commands is:\n"
        "  1. Kick off with Bash(run_in_background: true) writing to the capture file\n"
        "  2. Start a Monitor tailing that file with a line-buffered progress/failure filter\n"
        "  3. On Monitor wakes, relay the matched line verbatim\n\n"
        "If no streaming surface exists, use the fallback cadence: 60s -> 90s -> 120s -> max ~300s.\n"
        "Never peek faster than 60 seconds.\n\n"
        "Options:\n"
        f"  1. Switch to Monitor — see runtime/harness/claude/rules/session.md '## Tool Constraints'\n"
        "  2. Await the background-task completion notification instead of polling\n"
        f"  3. Override with `{SUPPRESSION_TOKEN}` if this is a post-capture inspection"
    )


def _format_sleep_reason(cadence: int, mode: str) -> str:
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    return (
        f"{verb}: sleep {cadence} && (cat|tail|head) — progress polling with N < 60s.\n\n"
        f"Fallback cadence when no streaming surface exists is 60s -> 90s -> 120s -> max ~300s.\n"
        f"Never check faster than 60 seconds.\n\n"
        "Prefer Monitor on the capture file or await the background completion notification.\n"
        f"Override with `{SUPPRESSION_TOKEN}` only for genuine post-capture inspection."
    )


def _format_monitor_duplicate_reason(
    capture_file: str,
    prior_tool_use_id: str,
    suppressed_attempt: bool,
    mode: str,
) -> str:
    """Reason text for the duplicate-Monitor rule (mode-pinned warn/deny).

    ``# lint:no-monitor-duplicate-check`` is honoured ONLY as audit evidence
    and the rule still denies in ``deny`` mode. ``prior_tool_use_id`` names
    the earliest Monitor in
    this session that targeted the same capture; the prior Monitor may
    be still armed or already completed — either way, re-arming is the
    wake-loop bug.
    """
    prior_id = prior_tool_use_id or "<prior-monitor-id>"
    raw_capture = _raw_capture_hint(capture_file)
    body = (
        "Second Monitor arming against a capture file that has already "
        "been targeted by Monitor in this session.\n\n"
        f"Target capture: {capture_file}\n"
        f"Earlier Monitor: {prior_id}\n\n"
        "Monitor is fire-once-per-capture for the whole session, not "
        "just while a Monitor is still armed. Monitor's tool_use "
        "completes within ~0.3s of setup; the underlying watcher "
        "subprocess keeps following the capture file independently. "
        "Re-arming Monitor against the same capture spawns a fresh "
        "watcher subprocess, leaks the prior one (no reader, no SIGTERM), "
        "and creates the 'dozens of shells running' pile-up that "
        "operational data showed accumulating during multi-minute bg "
        "commands. A second Monitor against the same capture (identical "
        "filter, different filter, or a fresh tail -f / watch_tail) is "
        "always a wake-loop re-arm.\n\n"
        "This rule has NO override — re-arming Monitor against a "
        "previously-targeted capture has no legitimate use case. The "
        f"`{MONITOR_DUPLICATE_SUPPRESSION_TOKEN}` token is honoured ONLY "
        "as audit evidence; it does NOT unblock this rule.\n\n"
        "Options:\n"
        "  1. If a Monitor against this capture is still armed, wait for "
        "its next wake — the existing watcher is the progress surface; "
        "matched lines arrive as wake events without re-arming\n"
        "  2. Run substantive parallel work (Read, Edit, unrelated Bash) "
        "in the meantime — that is fine and encouraged\n"
        f"  3. If the bg command has finished, read `tail -80 {raw_capture}` "
        "once for the post-completion inspection; do not arm another "
        "Monitor against the progress capture"
    )
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    if suppressed_attempt:
        return (
            f"{verb}: " + body
            + f"\n\nSuppression token `{MONITOR_DUPLICATE_SUPPRESSION_TOKEN}` "
            "was detected on this command and recorded for audit, but it "
            "does NOT unblock this rule."
        )
    return f"{verb}: " + body


def _build_context(tool_name: str, command: str, capture_file: Optional[str]) -> dict:
    ctx = {"tool": tool_name}
    if capture_file:
        ctx["capture_file"] = capture_file
    if command:
        ctx["command_snippet"] = command[:256]
    return ctx


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _emit_audit_event(
    payload: dict,
    tool_name: str,
    reason: str,
    mode: str,
    context: dict,
    outcome: str = "denied",
) -> None:
    """Emit a ``HarnessToolCallDenied`` audit event with mode-aware context.

    ``outcome`` selects the recorded event outcome. ``"denied"`` is the
    default. ``"suppression_attempted"`` is used by audit-only suppression
    tokens, such as duplicate-Monitor's token.

    The ``[outcome=...]`` annotation is appended to ``reason`` only for
    non-default outcomes so reviewers can grep distinguishable surfaces;
    the legacy ``"denied"`` reason format is unchanged.
    """
    # Imported locally so module load does not depend on the harness package.
    try:
        from runtime.harness.hook_runner.telemetry import emit_denial_event
    except Exception:
        return

    session_id = payload.get("session_id") or ""
    tool_use_id = payload.get("tool_use_id") or ""
    turn_id = payload.get("turn_id") or payload.get("message_id") or ""
    command_snippet = _extract_command(payload) or ""
    annotated_reason = f"[mode={mode}] {reason}"
    if outcome and outcome != "denied":
        annotated_reason = f"[mode={mode}][outcome={outcome}] {reason}"
    try:
        emit_denial_event(
            hook=HOOK_NAME,
            tool=tool_name or "Bash",
            check_id=CHECK_ID,
            reason=annotated_reason,
            session_id=session_id if isinstance(session_id, str) else "",
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            turn_id=turn_id if isinstance(turn_id, str) else "",
            command_snippet=command_snippet,
            outcome=outcome or "denied",
        )
    except Exception:
        pass

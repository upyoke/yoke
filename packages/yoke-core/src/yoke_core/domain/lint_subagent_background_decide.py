"""Reason formatter for the subagent-background lint.

Split from :mod:`yoke_core.domain.lint_subagent_background` so the
entry-point stays under the 350-line file cap (mirroring the
``lint_long_command_polling_decide`` split). Pure command/payload
introspection helpers live alongside the entry point; this module owns
the rendered-output side of the lint.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.lint_subagent_background_constants import SUPPRESSION_TOKEN


__all__ = [
    "format_reason",
]


def format_reason(
    *,
    tool_name: str,
    command: str,
    watcher: Optional[str],
    run_in_background: bool,
    suppressed: bool,
) -> str:
    """Render the plain operator-facing deny reason.

    The text is intentionally long so a single deny event is enough to
    explain what fired, the architectural reason, the canonical
    workaround, and the suppression-token semantics.
    """
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
        "  yoke watch pytest -- <pytest args>\n"
        "  yoke watch merge merge-item -- <args>\n"
        "Each blocks foreground in one Bash call, writes raw + filtered "
        "captures under the helper-resolved scratch root "
        "(`project_scratch_dir.watcher_capture_path(...)`), and exits "
        "before the turn does. The wrapper prints the raw-capture path "
        "on exit — inspect with `tail -80 <raw-capture>` after completion.\n\n"
        "If the turn budget cannot accommodate the foreground run, ask "
        "the parent orchestrator for a tighter dispatch scope. Growing "
        "the budget to fit a self-armed background pattern is not a "
        "workaround. See `.yoke/docs/agents/rules/claude-long-commands.md` "
        "`## Subagents` for the full rule."
    )
    text = "DENIED: " + body + guidance
    if suppressed:
        text += (
            f"\n\nSuppression token `{SUPPRESSION_TOKEN}` was detected "
            "and recorded for audit, but it does NOT unblock this rule. "
            "Run the command foreground instead."
        )
    return text

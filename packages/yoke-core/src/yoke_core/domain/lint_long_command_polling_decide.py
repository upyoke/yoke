"""Output-side helpers for the polling lint: reasons, context, deny.

Sibling of ``lint_long_command_polling`` (the hook entry point) and
``lint_long_command_polling_evaluate`` (the verdict logic). This module
isolates everything that builds output:

- ``_format_sleep_reason`` /
  ``_format_github_poll_loop_reason`` / ``_format_monitor_duplicate_reason`` — operator-facing reason text rendered with
  the verdict (``DENIED`` vs ``POLLING ANTI-PATTERN``).
- ``_build_context`` — the structured context dict returned with the
  verdict.

The formatters return plain reasons; decision_render owns harness output.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.lint_long_command_polling_constants import (
    MONITOR_DUPLICATE_SUPPRESSION_TOKEN,
)


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


def _format_sleep_reason(cadence: int, mode: str) -> str:
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    return (
        f"{verb}: sleep {cadence} followed by a registered capture read — progress polling with N < 60s.\n\n"
        f"Fallback cadence when no streaming surface exists is 60s -> 90s -> 120s -> max ~300s.\n"
        f"Never check faster than 60 seconds.\n\n"
        "In verified background-wake mode, await Monitor/completion; otherwise keep the original foreground wait active."
    )


def _format_github_poll_loop_reason(mode: str) -> str:
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    return (
        f"{verb}: shell loop polling GitHub for a CI run.\n\n"
        "A CI run Yoke dispatched for this session (`yoke watch pytest`, "
        "`yoke qa case run`, `yoke merge item`) has a recorded wait: its "
        "verdict wakes this session with the command that re-enters it. "
        "A polling loop holds the turn, so steering messages and that wake "
        "cannot reach you. This rule has no override.\n\n"
        "Options:\n"
        "  1. End the turn; the verdict wakes you\n"
        "  2. To await one run by exact commit in this turn, run "
        "`yoke watch ci-run -- REF`"
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
    from yoke_contracts.harness_wake_capability import (
        wake_capability_for_mechanism,
    )

    monitor = wake_capability_for_mechanism("Monitor")
    limit = (monitor.idle_wake_subscription_limit_seconds if monitor else None) or 0
    deadline = (
        f"{monitor.idle_wake_deadline_parameter}={limit * 1000}" if monitor else ""
    )
    raw_capture = _raw_capture_hint(capture_file)
    body = (
        "Second Monitor arming against a capture file whose earlier "
        "Monitor in this session may still be subscribed.\n\n"
        f"Target capture: {capture_file}\n"
        f"Earlier Monitor: {prior_id}\n\n"
        "Monitor is armed once per capture for as long as its subscription "
        f"can live (at most {limit // 60} minutes). Monitor's tool_use "
        "completes within ~0.3s of setup; the underlying watcher "
        "subprocess keeps following the capture file independently. "
        "Re-arming Monitor against the same capture spawns a fresh "
        "watcher subprocess, leaks the prior one (no reader, no SIGTERM), "
        "and creates the 'dozens of shells running' pile-up that "
        "operational data showed accumulating during multi-minute bg "
        "commands. A second Monitor against the same capture (identical "
        "filter, different filter, or a fresh tail -f / watch_tail) is "
        "always a wake-loop re-arm.\n\n"
        "This rule has NO override — re-arming a live subscription has no "
        "legitimate use case. The "
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
        "Monitor against the progress capture\n"
        "  4. If the earlier Monitor's expiry notice arrived while the bg "
        "command still runs, re-arm this same tail once that subscription "
        f"is {limit // 60} minutes old, and arm with {deadline} so expiry "
        "and re-arm line up; never relaunch the wrapper"
    )
    verb = "DENIED" if mode == "deny" else "POLLING ANTI-PATTERN"
    if suppressed_attempt:
        return (
            f"{verb}: "
            + body
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

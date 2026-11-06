"""Output-side helpers for the polling lint: reasons, context, deny.

Sibling of ``lint_long_command_polling`` (the hook entry point) and
``lint_long_command_polling_evaluate`` (the verdict logic). This module
isolates everything that builds output:

- ``_format_sleep_reason`` /
  ``_format_github_poll_loop_reason`` / ``_format_monitor_duplicate_reason`` — operator-facing ``DENIED`` reason text.
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


def _format_sleep_reason(cadence: int) -> str:
    return (
        f"DENIED: sleep {cadence} followed by a registered capture read — progress polling with N < 60s.\n\n"
        f"Fallback cadence when no streaming surface exists is 60s -> 90s -> 120s -> max ~300s.\n"
        f"Never check faster than 60 seconds.\n\n"
        "In verified background-wake mode, await Monitor/completion; otherwise keep the original foreground wait active."
    )


def _format_github_poll_loop_reason() -> str:
    return (
        "DENIED: shell loop polling GitHub for a CI run.\n\n"
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
    deadline: str,
) -> str:
    """Name the real subscription deadline and the safe re-arm action."""
    raw_capture = _raw_capture_hint(capture_file)
    body = (
        "DENIED: duplicate live Monitor subscription.\n"
        f"Target capture: {capture_file}\n"
        f"Earlier Monitor: {prior_tool_use_id}\n"
        f"Effective deadline: {deadline}\n\n"
        "Wait for the existing subscription's wake or do unrelated work. "
        "Its setup call completing does not end the subscription. "
        "After its expiry notice, re-arm this same tail; never relaunch "
        "the wrapper. If the command finished, inspect "
        f"`tail -80 {raw_capture}` once. "
        "This rule has no override; the suppression token does NOT unblock it."
    )
    if suppressed_attempt:
        body += f" {MONITOR_DUPLICATE_SUPPRESSION_TOKEN} recorded for audit."
    return body


def _build_context(tool_name: str, command: str, capture_file: Optional[str]) -> dict:
    ctx = {"tool": tool_name}
    if capture_file:
        ctx["capture_file"] = capture_file
    if command:
        ctx["command_snippet"] = command[:256]
    return ctx

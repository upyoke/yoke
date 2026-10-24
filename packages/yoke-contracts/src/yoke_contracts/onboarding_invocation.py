"""Render the installed onboarding skill in the receiving harness."""

from __future__ import annotations

from yoke_contracts.executor_labels import canonical_harness_id


def onboard_command(harness_id: str | None, arguments: str = "") -> str:
    """Use known native syntax, or explicitly label the supported alternatives."""
    suffix = f" {arguments}" if arguments else ""
    try:
        family = canonical_harness_id(harness_id)
    except ValueError:
        family = None
    if family == "codex":
        return f"$yoke onboard{suffix}"
    if family in ("claude-code", "cursor"):
        return f"/yoke onboard{suffix}"
    return f"Codex: $yoke onboard{suffix}; Claude Code/Cursor: /yoke onboard{suffix}"

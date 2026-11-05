"""Render the installed onboarding skill command."""

from __future__ import annotations


def onboard_command(harness_id: str | None, arguments: str = "") -> str:
    """Use the same skill syntax for every receiving harness."""
    suffix = f" {arguments}" if arguments else ""
    return f"/yoke onboard{suffix}"

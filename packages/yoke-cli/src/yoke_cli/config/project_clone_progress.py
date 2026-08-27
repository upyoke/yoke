"""User-facing progress copy for anonymous and App-authorized clones."""

from __future__ import annotations

from typing import Protocol


class _CloneOutcome(Protocol):
    used_token: bool


def clone_progress_lines(repo: str, outcome: _CloneOutcome) -> list[str]:
    """Return the approved informational lines for one clone step."""

    lines = [f"  Cloning {repo}…"]
    if outcome.used_token:
        lines.append("  Reading it with your connected GitHub App access.")
    lines.append("  ✓ Cloned.")
    return lines


__all__ = ["clone_progress_lines"]

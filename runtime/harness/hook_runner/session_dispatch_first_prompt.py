"""First-prompt marker primitives for Claude and Codex sessions.

Extracted from ``session_dispatch.py`` so the dispatcher stays under the
authored-file cap. The Claude marker path is resolved through the
project-scoped scratch helper rather than the legacy ``/tmp`` literal so
the scratch root is controlled by one resolver across the codebase.
"""

from __future__ import annotations

import os
from pathlib import Path

from yoke_core.domain.project_scratch_dir import hook_marker_path


__all__ = [
    "claude_prompt_marker_path",
    "is_first_prompt",
    "mark_first_prompt",
    "first_prompt",
]


def claude_prompt_marker_path(session_id: str) -> Path:
    """Return the per-session Claude first-prompt marker path."""

    return hook_marker_path(f"claude-prompt-{session_id}")


def is_first_prompt(session_id: str) -> bool:
    """Return True when no Claude first-prompt marker exists for *session_id*."""

    return not claude_prompt_marker_path(session_id).exists()


def mark_first_prompt(session_id: str) -> None:
    """Arm the Claude first-prompt marker for *session_id* (best-effort)."""

    marker = claude_prompt_marker_path(session_id)
    try:
        marker.touch()
    except OSError:
        pass


def first_prompt(session_id: str, *, codex: bool) -> bool:
    """Return True on the first prompt of *session_id*; arm the marker.

    Mirrors the Codex side via ``check_and_arm_marker`` and keeps the
    Claude side path-resolved through the scratch helper. Any filesystem
    error is swallowed — hook paths must never crash on /tmp weirdness.
    """

    if codex:
        from runtime.harness.codex.codex_hooks_payload import (
            check_and_arm_marker,
            prompt_marker_path,
        )

        return check_and_arm_marker(prompt_marker_path(session_id))
    marker = claude_prompt_marker_path(session_id)
    if os.path.exists(marker):
        return False
    try:
        marker.touch()
    except OSError:
        pass
    return True

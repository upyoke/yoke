"""Existence-only Claude transcript precondition for stopped-session wake."""

from __future__ import annotations

from pathlib import Path


def claude_project_storage_key(checkout: Path) -> str:
    """Return the ~/.claude/projects subdirectory key for a checkout root."""
    return checkout.resolve().as_posix().replace("/", "-")


def claude_session_transcript_path(checkout: Path, session_id: str) -> Path:
    """Return the Claude transcript file path for an exact session id."""
    return (
        Path.home()
        / ".claude"
        / "projects"
        / claude_project_storage_key(checkout)
        / f"{session_id}.jsonl"
    )


def claude_session_transcript_exists(checkout: Path, session_id: str) -> bool:
    """Return whether the stopped-session transcript file exists on this machine."""
    candidate = str(session_id or "").strip()
    if not candidate:
        return False
    try:
        return claude_session_transcript_path(checkout, candidate).is_file()
    except OSError:
        return False


__all__ = [
    "claude_project_storage_key",
    "claude_session_transcript_exists",
    "claude_session_transcript_path",
]

"""Existence-only Claude transcript precondition for stopped-session wake."""

from __future__ import annotations

from pathlib import Path


def claude_project_storage_key(checkout: Path) -> str:
    """Return the ~/.claude/projects subdirectory key for a checkout root."""
    # Claude uses JavaScript UTF-16 code units for replacement and hashing.
    encoded = checkout.resolve().as_posix().encode("utf-16-le", errors="surrogatepass")
    units = [int.from_bytes(encoded[i:i + 2], "little") for i in range(0, len(encoded), 2)]
    key = "".join(
        chr(unit) if 48 <= unit <= 57 or 65 <= unit <= 90 or 97 <= unit <= 122 else "-"
        for unit in units
    )
    if len(key) <= 200:
        return key
    hash_value = 0
    for unit in units:
        hash_value = (31 * hash_value + unit) & 0xFFFFFFFF
    if hash_value >= 0x80000000:
        hash_value -= 0x100000000
    remaining = abs(hash_value)
    suffix = ""
    while remaining:
        remaining, digit = divmod(remaining, 36)
        suffix = "0123456789abcdefghijklmnopqrstuvwxyz"[digit] + suffix
    return f"{key[:200]}-{suffix or '0'}"


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

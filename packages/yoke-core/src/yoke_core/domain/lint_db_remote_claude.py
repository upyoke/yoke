"""Remote-SSH Claude CLI classifier for the DB-command hook."""

from __future__ import annotations

import shlex

from yoke_core.domain import lint_config

REMOTE_CLAUDE_DENIAL = (
    "BLOCKED: Remote SSH command invokes claude as a CLI. "
    f"Set {lint_config.REMOTE_CLAUDE_CLI_GUARD}=warn in .yoke/lint-config "
    "only for operator-attended remote smoke tests."
)


def remote_claude_cli_state(
    command: str,
    payload: object | None = None,
) -> tuple[bool, bool]:
    """Return ``(seen_remote_claude, softened_by_lint_config)``."""
    claude_segments = [
        segment for segment in _top_level_shell_segments(command)
        if "claude" in segment
    ]
    is_remote = bool(claude_segments) and all(
        _command_basename(segment) == "ssh" for segment in claude_segments
    )
    if not is_remote:
        return False, False
    try:
        mode = lint_config.resolve_mode_for_payload(
            lint_config.REMOTE_CLAUDE_CLI_GUARD, payload,
        )
    except Exception:
        mode = lint_config.DENY
    return True, mode == lint_config.WARN


def _top_level_shell_segments(text: str) -> list[str]:
    segments: list[str] = []
    buf: list[str] = []
    quote = None
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            buf.append(ch)
            escaped = True
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            buf.append(ch)
            quote = ch
            continue
        if ch in ";&|\n":
            _append_segment(segments, buf)
            buf = []
            continue
        buf.append(ch)
    _append_segment(segments, buf)
    return segments


def _append_segment(segments: list[str], buf: list[str]) -> None:
    segment = "".join(buf).strip()
    if segment:
        segments.append(segment)


def _command_basename(segment: str) -> str:
    try:
        words = shlex.split(segment, posix=True)
    except Exception:
        words = segment.split()
    idx = 0
    while idx < len(words) and "=" in words[idx] and not words[idx].startswith("="):
        idx += 1
    if idx >= len(words):
        return ""
    first = words[idx]
    return first.rsplit("/", 1)[-1] if "/" in first else first

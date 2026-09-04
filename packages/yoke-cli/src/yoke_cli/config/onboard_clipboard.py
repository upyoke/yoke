"""Put an exact string on the system clipboard, and say what happened.

A full-screen terminal app owns the screen, so a one-time code or a long URL
can be read but not always selected. Each platform's own clipboard command
receives the string on stdin unchanged — no shortening, no re-wrapping — so
what lands on the clipboard is byte-for-byte what the screen shows.
"""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
import sys
from typing import Callable, Sequence

MACOS_PLATFORM = "darwin"

# The first command present on the machine wins: macOS ships ``pbcopy``,
# Wayland sessions ``wl-copy``, and X11 sessions ``xclip``.
MACOS_COMMANDS: tuple[tuple[str, ...], ...] = (("pbcopy",),)
OTHER_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("wl-copy",),
    ("xclip", "-selection", "clipboard"),
)

_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ClipboardCopyResult:
    """What happened when a string was handed to the clipboard.

    ``command`` names the clipboard program that accepted it; ``reason``
    carries every failed attempt in order, so a screen can say why nothing
    was copied instead of claiming a success that did not happen.
    """

    copied: bool
    command: str | None = None
    reason: str | None = None


def clipboard_commands(platform: str = sys.platform) -> tuple[tuple[str, ...], ...]:
    """Return the clipboard commands to try, most native first."""
    return MACOS_COMMANDS if platform == MACOS_PLATFORM else OTHER_COMMANDS


def copy(
    text: str,
    *,
    platform: str = sys.platform,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> ClipboardCopyResult:
    """Copy *text* verbatim, recording why each attempted command failed."""
    resolve = which or shutil.which
    execute = run or _run_clipboard_command
    attempts: list[str] = []
    for command in clipboard_commands(platform):
        if not resolve(command[0]):
            attempts.append(f"{command[0]} is not installed")
            continue
        try:
            completed = execute(command, text)
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append(f"{command[0]} failed: {type(exc).__name__}: {exc}")
            continue
        if completed.returncode == 0:
            return ClipboardCopyResult(copied=True, command=command[0])
        detail = (completed.stderr or "").strip() or "no output"
        attempts.append(f"{command[0]} exited {completed.returncode}: {detail}")
    return ClipboardCopyResult(copied=False, reason=_reason(attempts, platform))


def _reason(attempts: Sequence[str], platform: str) -> str:
    if attempts:
        return "; ".join(attempts)
    return f"no clipboard command is available on {platform}"


def _run_clipboard_command(
    command: Sequence[str], text: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        input=text,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


__all__ = [
    "ClipboardCopyResult",
    "MACOS_COMMANDS",
    "MACOS_PLATFORM",
    "OTHER_COMMANDS",
    "clipboard_commands",
    "copy",
]

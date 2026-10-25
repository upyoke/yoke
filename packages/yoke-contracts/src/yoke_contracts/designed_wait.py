"""Announce a wait that is silent by design before it starts.

Some commands wait on purpose without printing anything: a CI suite that
cannot conclude for minutes, a lock another process holds, a daemon that
has not answered yet. A reader of that output — an operator or an agent
following a watcher — cannot tell such a wait from a hang, so they
interrupt healthy work or spend effort investigating it. One line at the
start of the wait answers the question once: what is awaited, how often it
is checked, and the longest the wait may last. That bound is a timeout, not
an estimate: a CI suite that usually concludes in minutes may carry a
two-hour limit, so the line names it as a limit. Per-poll repetition is not
the fix; the bound is. A long wait that prints its own periodic status line says so
instead of promising silence, so a quiet capture there reads as stuck.

Every such line starts with :data:`DESIGNED_WAIT_PREFIX`, so watcher
wrappers pass it through to their reader even when they suppress routine
progress.
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

#: The opening words of every announcement; watchers key on them.
DESIGNED_WAIT_PREFIX = "Waiting by design:"


def format_duration(seconds: float) -> str:
    """Render *seconds* compactly: ``0.25s``, ``45s``, ``2m30s``, ``15m``, ``3h``."""
    if 0 < seconds < 1:
        return f"{seconds:g}s"
    total = max(0, int(round(seconds)))
    if total < 120:
        return f"{total}s"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs:
        parts.append(f"{secs}s")
    return "".join(parts)


def poll_every(seconds: float) -> str:
    """The cadence phrase for a wait that checks at a fixed interval."""
    return f"checks every {format_duration(seconds)}"


def designed_wait_line(
    subject: str,
    *,
    max_wait_seconds: float,
    cadence: Optional[str] = None,
    silent: bool = True,
) -> str:
    """The announcement for a wait on *subject* bounded by *max_wait_seconds*.

    *cadence* says how the wait checks its subject (see :func:`poll_every`);
    omit it for a wait that blocks on one call rather than polling. Pass
    ``silent=False`` for a wait whose cadence names its own status lines.
    """
    parts = [f"{DESIGNED_WAIT_PREFIX} {subject}"]
    if cadence:
        parts.append(cadence)
    parts.append(
        f"times out after {format_duration(max_wait_seconds)} at most "
        "(a limit, not an estimate)"
    )
    line = "; ".join(parts) + "."
    return f"{line} Silence while it waits is expected." if silent else line


def _write_stderr(line: str) -> None:
    sys.stderr.write(line + "\n")
    sys.stderr.flush()


def announce_designed_wait(
    subject: str,
    *,
    max_wait_seconds: float,
    cadence: Optional[str] = None,
    silent: bool = True,
    write: Optional[Callable[[str], None]] = None,
) -> str:
    """Write the announcement once and return it.

    *write* receives the line without a trailing newline; it defaults to a
    flushed stderr write so a command's machine-readable stdout stays clean.
    Pass a command's own output sink when it has one.
    """
    line = designed_wait_line(
        subject, max_wait_seconds=max_wait_seconds, cadence=cadence, silent=silent
    )
    (write or _write_stderr)(line)
    return line


__all__ = [
    "DESIGNED_WAIT_PREFIX",
    "announce_designed_wait",
    "designed_wait_line",
    "format_duration",
    "poll_every",
]

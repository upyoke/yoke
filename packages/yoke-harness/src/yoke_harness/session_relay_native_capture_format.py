"""Compose and read the one on-disk shape every native capture is written in.

A native's own words are the only account of why it refused, and until this
format existed on every spawn path they were thrown away: a process that died
before its first hook left a launch row reading ``succeeded`` and nothing to
read. One envelope, written by every harness adapter and by the supervisor
that watches a detached native, is what makes that account retrievable.

The envelope is deliberately readable by eye — an operator who has the file
should not need a parser — and deliberately self-describing about whether the
native is still running, because a capture is written while the turn is still
going and its reader has to tell "no output yet" from "exited silently".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re


CAPTURE_HEADER = b"YOKE NATIVE RELAY DIAGNOSTIC v1"
STDOUT_MARKER = b"--- stdout ---"
STDERR_MARKER = b"--- stderr ---"
STATE_RUNNING = "running"
STATE_EXITED = "exited"
#: Two independently capped 64-KiB native streams plus the header envelope.
CAPTURE_MAX_BYTES = 132 * 1024
STREAM_BUDGET_BYTES = 64 * 1024
#: One line of the native's own words, short enough to sit inside a fleet row.
TAIL_MAX_CHARS = 240
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class NativeCapture:
    """One native's retained streams and how it ended, as read back."""

    state: str
    stdout: bytes
    stderr: bytes
    exit_code: int | None = None
    exit_at: str | None = None

    @property
    def exited(self) -> bool:
        return self.state == STATE_EXITED

    @property
    def tail(self) -> str:
        """The last thing the native said, as one bounded printable line."""
        return capture_tail(self.stderr) or capture_tail(self.stdout)


def utc_stamp(now: float) -> str:
    """Render one capture timestamp in the stamp shape evidence carries."""
    return datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_tail(stream: bytes) -> str:
    """Return the last meaningful line of ``stream``, printable and bounded."""
    text = bytes(stream).decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        collapsed = _CONTROL_CHARACTERS.sub(" ", line).strip()
        if collapsed:
            return collapsed[:TAIL_MAX_CHARS]
    return ""


def compose_capture(
    *,
    stdout: bytes,
    stderr: bytes,
    state: str = STATE_EXITED,
    exit_code: int | None = None,
    exit_at: str | None = None,
) -> bytes:
    """Render one complete envelope, with both streams capped independently."""
    lines = [CAPTURE_HEADER, f"state: {state}".encode()]
    if state == STATE_EXITED:
        code = "unknown" if exit_code is None else str(int(exit_code))
        lines.append(f"exit-code: {code}".encode())
        if exit_at:
            lines.append(f"exit-at: {exit_at}".encode())
    header = b"\n".join(lines) + b"\n"
    return b"".join(
        (
            header,
            STDOUT_MARKER,
            b"\n",
            bytes(stdout)[:STREAM_BUDGET_BYTES],
            b"\n",
            STDERR_MARKER,
            b"\n",
            bytes(stderr)[:STREAM_BUDGET_BYTES],
        )
    )


def _header_values(header: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in header.splitlines()[1:]:
        name, separator, value = line.decode("utf-8", errors="replace").partition(":")
        if separator:
            values[name.strip()] = value.strip()
    return values


def parse_capture(payload: bytes) -> NativeCapture | None:
    """Read one envelope back, or ``None`` when the bytes are not one."""
    raw = bytes(payload)
    if not raw.startswith(CAPTURE_HEADER):
        return None
    header, separator, body = raw.partition(STDOUT_MARKER + b"\n")
    if not separator:
        return None
    stdout, stderr_separator, stderr = body.partition(b"\n" + STDERR_MARKER + b"\n")
    values = _header_values(header)
    raw_code = values.get("exit-code", "")
    try:
        exit_code = int(raw_code)
    except ValueError:
        exit_code = None
    return NativeCapture(
        state=values.get("state") or STATE_EXITED,
        stdout=stdout,
        stderr=stderr if stderr_separator else b"",
        exit_code=exit_code,
        exit_at=values.get("exit-at") or None,
    )


__all__ = [
    "CAPTURE_HEADER",
    "CAPTURE_MAX_BYTES",
    "STATE_EXITED",
    "STATE_RUNNING",
    "STDERR_MARKER",
    "STDOUT_MARKER",
    "STREAM_BUDGET_BYTES",
    "TAIL_MAX_CHARS",
    "NativeCapture",
    "capture_tail",
    "compose_capture",
    "parse_capture",
    "utc_stamp",
]

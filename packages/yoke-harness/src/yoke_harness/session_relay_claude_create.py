"""Whether a relay-owned Claude create refused before it could run.

A create no longer blocks on the native, so the poll that started it would
otherwise report every spawn as a success and leave a native that rejected its
own flags, model, or credentials to occupy the whole registration deadline
before anything noticed. The supervisor writes the capture the moment it starts
and marks it exited when the native ends, so a short read of that one file
separates "already refused" from "running" without waiting on either.
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Callable

from yoke_harness.session_relay_native_capture_format import NativeCapture
from yoke_harness.session_relay_native_diagnostics import read_native_capture


#: How long a create waits to see the native refuse outright. A native that
#: rejects its own invocation is gone in about a second; one still running at
#: the end of this window has started, and every later outcome belongs to
#: registration.
CLAUDE_CREATE_FAST_FAILURE_SECONDS = 6.0
_POLL_SECONDS = 0.2


def immediate_native_refusal(
    capture_path: Path,
    *,
    window_seconds: float = CLAUDE_CREATE_FAST_FAILURE_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> NativeCapture | None:
    """Return the capture of a native that already ended, else ``None``."""
    deadline = monotonic() + max(0.0, window_seconds)
    while True:
        capture = read_native_capture(capture_path)
        if capture is not None and capture.exited:
            return capture
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        sleeper(min(_POLL_SECONDS, remaining))


__all__ = [
    "CLAUDE_CREATE_FAST_FAILURE_SECONDS",
    "immediate_native_refusal",
]

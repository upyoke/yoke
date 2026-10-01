"""Bound resident diagnostics without changing canonical hook evaluation."""

from __future__ import annotations

import fcntl
import os
import socket
import time
from pathlib import Path


WARNING_INTERVAL_SECONDS = 300
_PROBE_TIMEOUT_SECONDS = 0.2


def claim_fallback_warning(state_dir: Path) -> bool:
    """Claim one warning per interval across short-lived hook processes.

    Keep one timestamp in the existing evaluator state directory, rather
    than accumulating session markers. A contended or unwritable diagnostic
    must never delay or prevent the canonical fallback; Doctor can still
    report the live socket's availability independently of this timestamp.
    """
    try:
        fd = os.open(
            state_dir / "fallback-warning",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "r+", encoding="utf-8") as state:
            fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
            now = time.time()
            try:
                previous = float(state.read(64))
            except (ValueError, UnicodeError):
                previous = 0.0
            if 0 <= now - previous < WARNING_INTERVAL_SECONDS:
                return False
            state.seek(0)
            state.write(str(now))
            state.truncate()
            return True
    except OSError:
        return False


def resident_socket_problem(socket_path: Path) -> str:
    """Probe the listener without starting a resident or evaluating a hook."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(_PROBE_TIMEOUT_SECONDS)
            peer.connect(str(socket_path))
    except OSError as exc:
        return f"YOKE_HOOK_RESIDENT_UNREACHABLE: {type(exc).__name__} at {socket_path}"
    return ""

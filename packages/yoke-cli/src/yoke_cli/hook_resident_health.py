"""Bound resident diagnostics without changing canonical hook evaluation."""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from yoke_contracts import platform_file_lock


WARNING_INTERVAL_SECONDS = 300


def claim_fallback_warning(state_dir: Path) -> bool:
    """Claim one warning per interval across short-lived hook processes.

    Keep one timestamp in the existing evaluator state directory, rather
    than accumulating session markers. A contended or unwritable diagnostic
    must never delay or prevent the canonical fallback; Doctor can still
    report the live socket's availability independently of this timestamp.
    """
    try:
        state_path = state_dir / "fallback-warning"
        if state_path.is_symlink():
            return False
        fd = os.open(
            state_path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "r+", encoding="utf-8") as state:
            platform_file_lock.acquire_exclusive_nonblocking(state.fileno())
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


def resident_revision_problem(socket_path: Path, expected: str) -> str:
    """Read loaded identity without evaluating hooks or restarting the process."""
    if not hasattr(socket, "AF_UNIX"):
        return "YOKE_HOOK_RESIDENT_UNSUPPORTED: Unix-domain sockets unavailable"
    from yoke_contracts.hook_evaluator_protocol import receive_frame, send_frame
    from yoke_contracts.hook_evaluator_protocol import HookEvaluatorProtocolError

    from yoke_contracts.engine_version import installed_engine_version

    version = installed_engine_version()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(1.0)
            peer.connect(str(socket_path))
            send_frame(peer, {"kind": "health"})
            response = receive_frame(peer)
    except (OSError, HookEvaluatorProtocolError) as exc:
        return f"YOKE_HOOK_RESIDENT_UNREACHABLE: {type(exc).__name__}"
    loaded = response.get("loaded_revision")
    if response.get("status") != "health":
        return (
            "YOKE_HOOK_REVISION_UNKNOWN: resident health requires the protocol from "
            f"installed build {expected if expected != 'unknown' else version or 'unknown'}"
        )
    if expected and expected != "unknown":
        if loaded != expected:
            return f"YOKE_HOOK_VERSION_MISMATCH: loaded {loaded}, installed {expected}"
    elif version and version != "0.1.0":
        observed = response.get("engine_version")
        if observed != version:
            return f"YOKE_HOOK_VERSION_MISMATCH: loaded {observed or 'unknown'}, installed {version}"
    else:
        return "YOKE_HOOK_REVISION_UNKNOWN: installed build identity is unavailable"
    return ""

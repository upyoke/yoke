"""Terminal transcript and screenshot capture helpers for SSH host control."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shlex
import subprocess
import time
from typing import Callable
from uuid import uuid4


RunRemote = Callable[..., subprocess.CompletedProcess[str]]


def verify_terminal_bridge(
    run: RunRemote,
) -> tuple[bool, dict[str, bool], str | None]:
    """Exercise PTY, Terminal automation, and screenshot capture together."""
    session = "yoke-bridge-" + uuid4().hex[:12]
    sentinel = "yoke-terminal-bridge-ready"
    remote = f"/tmp/{session}.png"
    checks = {
        "pty": False,
        "terminal_control": False,
        "screenshot_capture": False,
        "sample_artifact_retained": False,
    }
    try:
        started = run(
            f"tmux new-session -d -s {shlex.quote(session)} "
            + shlex.quote(f"printf '{sentinel}\\n'; sleep 15"),
            timeout=20,
        )
        if started.returncode:
            return False, checks, "terminal_bridge_unavailable"
        checks["pty"] = True
        attach = f"tmux attach-session -t {session}"
        apple = 'tell application "Terminal" to do script ' + json.dumps(attach)
        attached = run(
            "/usr/bin/osascript -e " + shlex.quote(apple),
            timeout=20,
        )
        if attached.returncode:
            return False, checks, "terminal_bridge_unavailable"
        checks["terminal_control"] = (
            wait_for_text(
                run,
                session=session,
                expected=sentinel,
                timeout_seconds=5,
            )
            is not None
        )
        captured = run(
            f"/usr/sbin/screencapture -x {shlex.quote(remote)}; "
            f"test -s {shlex.quote(remote)}",
            timeout=30,
        )
        checks["screenshot_capture"] = captured.returncode == 0
        ok = all(
            checks[key]
            for key in ("pty", "terminal_control", "screenshot_capture")
        )
        return (
            ok,
            checks,
            None if ok else "terminal_bridge_unavailable",
        )
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        run(
            f"tmux kill-session -t {shlex.quote(session)}",
            timeout=10,
        )


def wait_for_text(
    run: RunRemote,
    *,
    session: str,
    expected: str,
    timeout_seconds: int,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = run(
            f"tmux capture-pane -t {shlex.quote(session)} -p -S -",
            timeout=10,
        )
        if result.returncode == 0 and expected in result.stdout:
            return result.stdout
        time.sleep(0.25)
    return None


def capture_screen(
    run: RunRemote,
    *,
    session: str,
    key: str,
    evidence_root: Path,
) -> Path | None:
    remote = f"/tmp/{session}-{key}.png"
    result = run(
        f"/usr/sbin/screencapture -x {shlex.quote(remote)} && "
        f"/usr/bin/base64 < {shlex.quote(remote)}; "
        f"rm -f {shlex.quote(remote)}",
        timeout=30,
    )
    if result.returncode or not result.stdout.strip():
        return None
    try:
        payload = base64.b64decode(result.stdout)
    except ValueError:
        return None
    path = evidence_root / f"{key}.png"
    path.write_bytes(payload)
    return path


__all__ = ["capture_screen", "verify_terminal_bridge", "wait_for_text"]

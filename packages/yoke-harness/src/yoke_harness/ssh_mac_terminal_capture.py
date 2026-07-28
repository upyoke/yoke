"""Client-side terminal transcript and screenshot capture over SSH."""

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
TerminalBackend = str


def detect_terminal_backend(run: RunRemote) -> TerminalBackend | None:
    """Return the first supported PTY multiplexer installed on the host."""
    result = run(
        "if command -v tmux >/dev/null 2>&1; then printf tmux; "
        "elif command -v screen >/dev/null 2>&1; then printf screen; fi",
        timeout=10,
    )
    if result.returncode:
        return None
    backend = result.stdout.strip()
    return backend if backend in {"tmux", "screen"} else None


def _start_session_command(
    backend: TerminalBackend,
    *,
    session: str,
    command: str,
) -> str:
    if backend == "tmux":
        return f"tmux new-session -d -s {shlex.quote(session)} " + shlex.quote(command)
    if backend == "screen":
        return f"screen -dmS {shlex.quote(session)} /bin/sh -lc " + shlex.quote(command)
    raise ValueError(f"unsupported terminal backend {backend!r}")


def _attach_command(backend: TerminalBackend, *, session: str) -> str:
    if backend == "tmux":
        return f"tmux attach-session -t {session}"
    if backend == "screen":
        return f"screen -r {session}"
    raise ValueError(f"unsupported terminal backend {backend!r}")


def send_terminal_input(
    run: RunRemote,
    *,
    backend: TerminalBackend,
    session: str,
    text: str,
) -> bool:
    """Send one line of text through a closed supported backend."""
    if backend == "tmux":
        command = (
            f"tmux send-keys -t {shlex.quote(session)} -- "
            + shlex.quote(text)
            + " Enter"
        )
    elif backend == "screen":
        command = f"screen -S {shlex.quote(session)} -p 0 -X stuff " + shlex.quote(
            text + "\n"
        )
    else:
        raise ValueError(f"unsupported terminal backend {backend!r}")
    return run(command, timeout=10).returncode == 0


def close_terminal_session(
    run: RunRemote,
    *,
    backend: TerminalBackend,
    session: str,
) -> None:
    """Best-effort cleanup for one supported backend session."""
    if backend == "tmux":
        command = f"tmux kill-session -t {shlex.quote(session)}"
    elif backend == "screen":
        command = f"screen -S {shlex.quote(session)} -X quit"
    else:
        return
    run(command, timeout=10)


def resize_terminal_session(
    run: RunRemote,
    *,
    backend: TerminalBackend,
    session: str,
    columns: int,
    rows: int,
) -> bool:
    """Resize one already-created terminal session through its native backend."""
    if backend == "tmux":
        command = f"tmux resize-window -t {shlex.quote(session)} -x {columns} -y {rows}"
    elif backend == "screen":
        command = f"screen -S {shlex.quote(session)} -p 0 -X width {columns} {rows}"
    else:
        raise ValueError(f"unsupported terminal backend {backend!r}")
    return run(command, timeout=10).returncode == 0


def verify_terminal_bridge(
    run: RunRemote,
    *,
    backend: TerminalBackend = "tmux",
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
            _start_session_command(
                backend,
                session=session,
                command=f"printf '{sentinel}\\n'; sleep 15",
            ),
            timeout=20,
        )
        if started.returncode:
            return False, checks, "terminal_bridge_unavailable"
        checks["pty"] = True
        attach = _attach_command(backend, session=session)
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
                backend=backend,
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
            checks[key] for key in ("pty", "terminal_control", "screenshot_capture")
        )
        return (
            ok,
            checks,
            None if ok else "terminal_bridge_unavailable",
        )
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
        close_terminal_session(
            run,
            backend=backend,
            session=session,
        )


def wait_for_text(
    run: RunRemote,
    *,
    backend: TerminalBackend = "tmux",
    session: str,
    expected: str,
    timeout_seconds: int,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if backend == "tmux":
            command = f"tmux capture-pane -t {shlex.quote(session)} -p -S -"
        elif backend == "screen":
            remote = f"/tmp/{session}-transcript.txt"
            command = (
                f"screen -S {shlex.quote(session)} -p 0 -X hardcopy -h "
                f"{shlex.quote(remote)}; "
                f"cat {shlex.quote(remote)} 2>/dev/null; "
                f"rm -f {shlex.quote(remote)}"
            )
        else:
            raise ValueError(f"unsupported terminal backend {backend!r}")
        result = run(command, timeout=10)
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


__all__ = [
    "RunRemote",
    "TerminalBackend",
    "capture_screen",
    "close_terminal_session",
    "detect_terminal_backend",
    "resize_terminal_session",
    "send_terminal_input",
    "verify_terminal_bridge",
    "wait_for_text",
]

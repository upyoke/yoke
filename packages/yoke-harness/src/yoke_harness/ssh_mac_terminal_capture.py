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
_TERMINAL_CAPTURE_TIMEOUT_SECONDS = 10
_TERMINAL_CAPTURE_POLL_SECONDS = 0.1


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


def open_terminal_window(
    run: RunRemote,
    *,
    command: str,
) -> int | None:
    """Run one command in a new Terminal window and return that window's id."""
    apple = "\n".join(
        [
            'tell application "Terminal"',
            f"do script {json.dumps(command)}",
            "return id of front window",
            "end tell",
        ]
    )
    result = run(
        "/usr/bin/osascript -e " + shlex.quote(apple),
        timeout=20,
    )
    try:
        window_id = int(result.stdout.strip())
    except (AttributeError, TypeError, ValueError):
        return None
    return window_id if result.returncode == 0 and window_id > 0 else None


def close_terminal_window(
    run: RunRemote,
    *,
    window_id: int | None,
) -> None:
    """Best-effort cleanup for one Terminal window opened by this executor."""
    if window_id is None:
        return
    apple = "\n".join(
        [
            'tell application "Terminal"',
            f"if exists window id {window_id} then",
            f"close window id {window_id}",
            "end if",
            "end tell",
        ]
    )
    run(
        "/usr/bin/osascript -e " + shlex.quote(apple),
        timeout=20,
    )


def _terminal_screenshot_payload(
    run: RunRemote,
    *,
    remote: str,
    window_id: int,
) -> str | None:
    """Capture through Terminal.app so macOS applies its Screen Recording grant."""
    shell_command = (
        f"/usr/sbin/screencapture -x -l {window_id} {shlex.quote(remote)}"
    )
    window_id = open_terminal_window(
        run,
        command=shell_command,
    )
    if window_id is None:
        return None
    try:
        deadline = time.monotonic() + _TERMINAL_CAPTURE_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            encoded = run(
                f"/bin/test -s {shlex.quote(remote)} && "
                f"/usr/bin/base64 < {shlex.quote(remote)}",
                timeout=10,
            )
            if encoded.returncode == 0 and encoded.stdout.strip():
                return encoded.stdout
            time.sleep(_TERMINAL_CAPTURE_POLL_SECONDS)
        return None
    finally:
        close_terminal_window(run, window_id=window_id)


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
    terminal_window_id: int | None = None
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
        terminal_window_id = open_terminal_window(
            run,
            command=attach,
        )
        if terminal_window_id is None:
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
        checks["screenshot_capture"] = (
            _terminal_screenshot_payload(
                run,
                remote=remote,
                window_id=terminal_window_id,
            )
            is not None
        )
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
        close_terminal_window(run, window_id=terminal_window_id)


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
    window_id: int,
) -> Path | None:
    remote = f"/tmp/{session}-{key}.png"
    try:
        encoded = _terminal_screenshot_payload(
            run,
            remote=remote,
            window_id=window_id,
        )
        if encoded is None:
            return None
        try:
            payload = base64.b64decode(encoded)
        except ValueError:
            return None
    finally:
        run(f"rm -f {shlex.quote(remote)}", timeout=10)
    path = evidence_root / f"{key}.png"
    path.write_bytes(payload)
    return path


__all__ = [
    "RunRemote",
    "TerminalBackend",
    "capture_screen",
    "close_terminal_window",
    "close_terminal_session",
    "detect_terminal_backend",
    "open_terminal_window",
    "resize_terminal_session",
    "send_terminal_input",
    "verify_terminal_bridge",
    "wait_for_text",
]

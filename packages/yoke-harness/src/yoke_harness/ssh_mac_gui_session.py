"""Run bounded host commands in the logged-in macOS GUI session."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import shlex
import subprocess
import time
from typing import Sequence
from uuid import uuid4

from yoke_harness.ssh_mac_terminal_app import (
    RunRemote,
    close_terminal_app_window,
    open_terminal_app_window,
)


_BRIDGE_POLL_SECONDS = 0.1
_BRIDGE_FAILURE_EXIT_CODE = 125
_BRIDGE_TIMEOUT_EXIT_CODE = 124
GUI_SESSION_UNAVAILABLE_REASON = (
    "macOS GUI-session context was not obtained through Terminal.app"
)


@dataclass(frozen=True)
class MacosSessionContextFailure:
    """A recognized macOS failure caused by the caller's session context."""

    error_code: str
    reason: str


_KNOWN_FAILURES = (
    (
        ("could not create image from display",),
        MacosSessionContextFailure(
            "macos_window_server_context_unavailable",
            "macOS window-server context is unavailable to this process",
        ),
    ),
    (
        ("could not switch to audit session", "operation not permitted"),
        MacosSessionContextFailure(
            "macos_gui_audit_session_unavailable",
            "macOS GUI audit-session context is unavailable to this process",
        ),
    ),
    (
        ("user interaction is not allowed",),
        MacosSessionContextFailure(
            "macos_login_keychain_context_unavailable",
            "macOS login-keychain context is unavailable to this process",
        ),
    ),
    (
        ("errsecinteractionnotallowed",),
        MacosSessionContextFailure(
            "macos_login_keychain_context_unavailable",
            "macOS login-keychain context is unavailable to this process",
        ),
    ),
    (
        ("oauth", "expired", "unrefreshable"),
        MacosSessionContextFailure(
            "macos_login_keychain_context_unavailable",
            "macOS login-keychain context is unavailable to this process",
        ),
    ),
)


def classify_macos_session_context_failure(
    result: subprocess.CompletedProcess[str],
) -> MacosSessionContextFailure | None:
    """Translate known privilege-poor SSH failures into accurate causes."""
    text = "\n".join((result.stdout or "", result.stderr or "")).casefold()
    if GUI_SESSION_UNAVAILABLE_REASON.casefold() in text:
        return MacosSessionContextFailure(
            "macos_gui_session_context_unavailable",
            GUI_SESSION_UNAVAILABLE_REASON,
        )
    for fragments, failure in _KNOWN_FAILURES:
        if all(fragment in text for fragment in fragments):
            return failure
    return None


def _bridge_failure(
    argv: tuple[str, ...],
    *,
    detail: str,
    timeout: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=argv,
        returncode=(
            _BRIDGE_TIMEOUT_EXIT_CODE if timeout else _BRIDGE_FAILURE_EXIT_CODE
        ),
        stdout="",
        stderr=f"{GUI_SESSION_UNAVAILABLE_REASON}: {detail}",
    )


def _read_remote_text(run: RunRemote, path: str) -> str | None:
    result = run(
        f"/usr/bin/base64 < {shlex.quote(path)}",
        timeout=10,
    )
    if result.returncode:
        return None
    try:
        payload = base64.b64decode(result.stdout.strip())
    except (ValueError, TypeError):
        return None
    return payload.decode("utf-8", errors="replace")


def run_terminal_app_command(
    run: RunRemote,
    *,
    argv: Sequence[str],
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Execute argv through Terminal.app and return its output and exit code."""
    normalized = tuple(str(value) for value in argv)
    if not normalized or any(not value for value in normalized):
        raise ValueError("GUI-session command requires non-empty argv")
    if timeout < 1:
        raise ValueError("GUI-session command timeout must be positive")
    session = "yoke-gui-session-" + uuid4().hex[:12]
    stdout_path = f"/tmp/{session}.stdout"
    stderr_path = f"/tmp/{session}.stderr"
    status_path = f"/tmp/{session}.exit"
    paths = (stdout_path, stderr_path, status_path)
    command = shlex.join(normalized)
    wrapped = (
        "umask 077; set +e; ( "
        + command
        + " ) > "
        + shlex.quote(stdout_path)
        + " 2> "
        + shlex.quote(stderr_path)
        + "; gui_rc=$?; /usr/bin/printf '%s\\n' \"$gui_rc\" > "
        + shlex.quote(status_path)
    )
    window_id: int | None = None
    try:
        window_id = open_terminal_app_window(run, command=wrapped)
        if window_id is None:
            return _bridge_failure(normalized, detail="Terminal.app launch failed")
        deadline = time.monotonic() + timeout
        exit_code: int | None = None
        while time.monotonic() < deadline:
            status = run(
                "if /bin/test -f "
                + shlex.quote(status_path)
                + "; then /bin/cat "
                + shlex.quote(status_path)
                + "; else exit 1; fi",
                timeout=10,
            )
            if status.returncode == 0 and status.stdout.strip():
                try:
                    exit_code = int(status.stdout.strip().splitlines()[-1])
                except ValueError:
                    return _bridge_failure(
                        normalized,
                        detail="Terminal.app returned an invalid exit status",
                    )
                break
            time.sleep(_BRIDGE_POLL_SECONDS)
        if exit_code is None:
            return _bridge_failure(
                normalized,
                detail="Terminal.app command timed out",
                timeout=True,
            )
        stdout = _read_remote_text(run, stdout_path)
        stderr = _read_remote_text(run, stderr_path)
        if stdout is None or stderr is None:
            return _bridge_failure(
                normalized,
                detail="Terminal.app command output was unavailable",
            )
        return subprocess.CompletedProcess(
            args=normalized,
            returncode=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        run("/bin/rm -f " + shlex.join(paths), timeout=10)
        close_terminal_app_window(run, window_id=window_id)


__all__ = [
    "GUI_SESSION_UNAVAILABLE_REASON",
    "MacosSessionContextFailure",
    "classify_macos_session_context_failure",
    "run_terminal_app_command",
]

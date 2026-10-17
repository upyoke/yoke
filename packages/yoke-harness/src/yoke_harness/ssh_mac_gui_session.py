"""Run bounded host commands in the logged-in macOS GUI session."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import shlex
import subprocess
import time
from typing import Sequence
from uuid import uuid4

from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE,
    TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE,
    TERMINAL_WINDOW_ACCUMULATION_THRESHOLD,
)
from yoke_harness.ssh_mac_host_session_state import read_terminal_window_count
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


_LOGIN_KEYCHAIN_CONTEXT_FAILURE = MacosSessionContextFailure(
    "macos_login_keychain_context_unavailable",
    "macOS login-keychain context is unavailable to this process",
)

# Each row names output fragments, the diagnosis, and whether plain SSH exec
# is required: a GUI program's login prompt can be a real sign-in failure.
_KNOWN_FAILURES = (
    (
        ("could not create image from display",),
        MacosSessionContextFailure(
            "macos_window_server_context_unavailable",
            "macOS window-server context is unavailable to this process",
        ),
        False,
    ),
    (
        ("could not switch to audit session", "operation not permitted"),
        MacosSessionContextFailure(
            "macos_gui_audit_session_unavailable",
            "macOS GUI audit-session context is unavailable to this process",
        ),
        False,
    ),
    (
        ("user interaction is not allowed",),
        _LOGIN_KEYCHAIN_CONTEXT_FAILURE,
        False,
    ),
    (
        ("errsecinteractionnotallowed",),
        _LOGIN_KEYCHAIN_CONTEXT_FAILURE,
        False,
    ),
    (
        ("oauth", "expired", "unrefreshable"),
        _LOGIN_KEYCHAIN_CONTEXT_FAILURE,
        False,
    ),
    (
        ("login keychain is locked",),
        _LOGIN_KEYCHAIN_CONTEXT_FAILURE,
        True,
    ),
    (
        ("not logged in", "please run /login"),
        _LOGIN_KEYCHAIN_CONTEXT_FAILURE,
        True,
    ),
)


def classify_macos_session_context_failure(
    result: subprocess.CompletedProcess[str],
    *,
    ssh_exec: bool = False,
) -> MacosSessionContextFailure | None:
    """Translate known privilege-poor SSH failures into accurate causes."""
    text = "\n".join((result.stdout or "", result.stderr or "")).casefold()
    if GUI_SESSION_UNAVAILABLE_REASON.casefold() in text:
        return MacosSessionContextFailure(
            "macos_gui_session_context_unavailable",
            GUI_SESSION_UNAVAILABLE_REASON,
        )
    for fragments, failure, requires_ssh_exec in _KNOWN_FAILURES:
        if requires_ssh_exec and not ssh_exec:
            continue
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
    bounds: tuple[int, int, int, int] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute argv through Terminal.app, preserving empty option values."""
    normalized = tuple(str(value) for value in argv)
    if not normalized or not normalized[0]:
        raise ValueError("GUI-session command requires a non-empty executable")
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
        launch = open_terminal_app_window(
            run,
            command=wrapped,
            bounds=bounds,
        )
        window_id = launch.window_id
        if window_id is None:
            return _bridge_failure(
                normalized,
                detail=f"Terminal.app launch failed (osascript exit {launch.returncode}): "
                f"{launch.stderr or launch.stdout or 'no window id returned'}",
            )
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


# Long enough for a granted probe on a loaded host, short enough that a
# missing grant (which blocks osascript on a consent prompt) fails fast.
AUTOMATION_PROBE_TIMEOUT_SECONDS = 15
# AppleScript's own "AppleEvent timed out", raised inside the probe.
_APPLE_EVENT_TIMEOUT = "-1712"
# AppleScript's "not authorized to send Apple events", the grant's denial.
_APPLE_EVENT_DENIED = "-1743"


@dataclass(frozen=True)
class TerminalAutomationProbe:
    """What a command inside Terminal saw when it asked System Events to act.

    A denial and a timeout have different fixes, so each carries its own error
    code. A timeout also reads Terminal's window count: with hundreds of
    windows left by earlier runs, every command inside Terminal stalls and the
    grant is not the cause.
    """

    error_code: str | None
    detail: str
    terminal_windows: int | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None


def terminal_system_events_automation(run: RunRemote) -> TerminalAutomationProbe:
    """Ask System Events to act from inside Terminal.app and name the outcome."""
    result = run_terminal_app_command(
        run,
        argv=(
            "/usr/bin/osascript",
            "-e",
            'tell application "System Events" to count processes',
        ),
        timeout=AUTOMATION_PROBE_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return TerminalAutomationProbe(None, "")
    detail = (result.stderr or result.stdout or "").strip()[:200]
    if _APPLE_EVENT_DENIED in detail:
        return TerminalAutomationProbe(
            TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE,
            f"automation_missing:Terminal->System Events: {detail}",
        )
    timed_out = (
        result.returncode == _BRIDGE_TIMEOUT_EXIT_CODE or _APPLE_EVENT_TIMEOUT in detail
    )
    if not timed_out:
        return TerminalAutomationProbe(
            TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE,
            f"automation_failed:Terminal->System Events: exit "
            f"{result.returncode}: {detail}",
        )
    windows = read_terminal_window_count(run)
    if windows is not None and windows > TERMINAL_WINDOW_ACCUMULATION_THRESHOLD:
        return TerminalAutomationProbe(
            TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE,
            f"terminal_window_accumulation:{windows}: {detail}",
            windows,
        )
    return TerminalAutomationProbe(
        TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE,
        f"automation_timeout:Terminal->System Events: {detail}",
        windows,
    )


__all__ = [
    "AUTOMATION_PROBE_TIMEOUT_SECONDS",
    "GUI_SESSION_UNAVAILABLE_REASON",
    "MacosSessionContextFailure",
    "TerminalAutomationProbe",
    "classify_macos_session_context_failure",
    "run_terminal_app_command",
    "terminal_system_events_automation",
]

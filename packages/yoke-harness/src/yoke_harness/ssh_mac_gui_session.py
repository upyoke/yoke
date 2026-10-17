"""Run bounded host commands in the logged-in macOS GUI session."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import shlex
import subprocess
import time
from typing import Sequence
from uuid import uuid4

from yoke_harness.ssh_mac_process_tree import ProcessTreeStop, stop_process_tree
from yoke_harness.ssh_mac_terminal_app import (
    RunRemote,
    open_terminal_app_window,
)
from yoke_harness.ssh_mac_terminal_window_close import close_terminal_app_window


_BRIDGE_POLL_SECONDS = 0.1
_BRIDGE_FAILURE_EXIT_CODE = 125
GUI_COMMAND_TIMEOUT_EXIT_CODE = 124
# Named refusals a GUI-session command carries in its stderr.
GUI_COMMAND_TIMEOUT_STOPPED = "gui_command_timeout_stopped"
GUI_COMMAND_TIMEOUT_NOT_STOPPED = "gui_command_timeout_not_stopped"
GUI_COMMAND_WINDOW_NOT_CLOSED = "gui_command_window_not_closed"
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
            GUI_COMMAND_TIMEOUT_EXIT_CODE if timeout else _BRIDGE_FAILURE_EXIT_CODE
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


@dataclass
class _GuiWindow:
    """What the finally block needs to clean up after one command."""

    paths: tuple[str, ...]
    window_id: int | None = None
    keep_paths: bool = False


def _stop_timed_out_command(
    run: RunRemote,
    argv: tuple[str, ...],
    *,
    pid_path: str,
    window: _GuiWindow,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    """Stop the command the wait gave up on before its output is deleted.

    A command left running keeps writing into files the cleanup removed and
    keeps whatever it holds, such as a setup lock, until its own wait ends.
    """
    pid_text = (_read_remote_text(run, pid_path) or "").strip()
    stop = (
        stop_process_tree(run, int(pid_text))
        if pid_text.isdigit()
        else ProcessTreeStop(False, detail="the command never recorded its pid")
    )
    if stop.stopped:
        message = (
            f"{GUI_COMMAND_TIMEOUT_STOPPED}: the command did not finish within "
            f"{timeout}s; its process tree (pid {pid_text}) was stopped. Re-run "
            "with a longer --timeout-seconds if it was still making progress."
        )
    else:
        window.keep_paths = True
        reason = (
            f"processes {' '.join(map(str, stop.survivors))} survived TERM and KILL"
            if stop.survivors
            else stop.detail
        )
        message = (
            f"{GUI_COMMAND_TIMEOUT_NOT_STOPPED}: the command did not finish within "
            f"{timeout}s and could not be confirmed stopped ({reason}); its output "
            f"stays at {' '.join(window.paths)}. Stop it on the host "
            f"(pid {pid_text or 'unknown'}), read those files, then retry."
        )
    return subprocess.CompletedProcess(
        argv, GUI_COMMAND_TIMEOUT_EXIT_CODE, stdout="", stderr=message
    )


def _drive_window(
    run: RunRemote,
    argv: tuple[str, ...],
    *,
    wrapped: str,
    status_path: str,
    pid_path: str,
    window: _GuiWindow,
    timeout: int,
    bounds: tuple[int, int, int, int] | None,
) -> subprocess.CompletedProcess[str]:
    stdout_path, stderr_path = window.paths[:2]
    launch = open_terminal_app_window(run, command=wrapped, bounds=bounds)
    window.window_id = launch.window_id
    if window.window_id is None:
        return _bridge_failure(
            argv,
            detail=f"Terminal.app launch failed (osascript exit {launch.returncode}): "
            f"{launch.stderr or launch.stdout or 'no window id returned'}",
        )
    deadline = time.monotonic() + timeout
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
                    argv, detail="Terminal.app returned an invalid exit status"
                )
            break
        time.sleep(_BRIDGE_POLL_SECONDS)
    else:
        return _stop_timed_out_command(
            run, argv, pid_path=pid_path, window=window, timeout=timeout
        )
    stdout = _read_remote_text(run, stdout_path)
    stderr = _read_remote_text(run, stderr_path)
    if stdout is None or stderr is None:
        return _bridge_failure(
            argv, detail="Terminal.app command output was unavailable"
        )
    return subprocess.CompletedProcess(
        args=argv, returncode=exit_code, stdout=stdout, stderr=stderr
    )


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
    session = "/tmp/yoke-gui-session-" + uuid4().hex[:12]
    status_path, pid_path = f"{session}.exit", f"{session}.pid"
    window = _GuiWindow(
        paths=(f"{session}.stdout", f"{session}.stderr", status_path, pid_path)
    )
    # The command execs from a shell that first records its pid, so a timeout
    # can stop exactly the process tree this call started.
    command = shlex.join(
        ("/bin/sh", "-c", 'echo $$ > "$1"; shift; exec "$@"', "yoke-gui-session")
        + (pid_path,)
        + normalized
    )
    wrapped = (
        "umask 077; set +e; ( "
        + command
        + " ) > "
        + shlex.quote(window.paths[0])
        + " 2> "
        + shlex.quote(window.paths[1])
        + "; gui_rc=$?; /usr/bin/printf '%s\\n' \"$gui_rc\" > "
        + shlex.quote(status_path)
    )
    try:
        result = _drive_window(
            run,
            normalized,
            wrapped=wrapped,
            status_path=status_path,
            pid_path=pid_path,
            window=window,
            timeout=timeout,
            bounds=bounds,
        )
    finally:
        if not window.keep_paths:
            run("/bin/rm -f " + shlex.join(window.paths), timeout=10)
        closed = close_terminal_app_window(run, window_id=window.window_id)
    if closed:
        return result
    # The command's own answer stands; the leaked window is named beside it
    # because every one left open slows the commands that follow.
    leak = (
        f"{GUI_COMMAND_WINDOW_NOT_CLOSED}: Terminal window {window.window_id} "
        "stayed open after its command; run `yoke test-machine reset`, which "
        "quits Terminal, or close it at the host console"
    )
    stderr = f"{result.stderr.rstrip()}\n{leak}" if result.stderr else leak
    return subprocess.CompletedProcess(
        result.args, result.returncode, result.stdout, stderr
    )


__all__ = [
    "GUI_COMMAND_TIMEOUT_EXIT_CODE",
    "GUI_COMMAND_TIMEOUT_NOT_STOPPED",
    "GUI_COMMAND_TIMEOUT_STOPPED",
    "GUI_COMMAND_WINDOW_NOT_CLOSED",
    "GUI_SESSION_UNAVAILABLE_REASON",
    "MacosSessionContextFailure",
    "classify_macos_session_context_failure",
    "run_terminal_app_command",
]

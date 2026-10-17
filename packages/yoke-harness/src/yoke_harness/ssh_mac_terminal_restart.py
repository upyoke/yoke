"""Quit Terminal.app before a test-machine reset and relaunch it afterwards.

Every GUI-session command opens a Terminal window. A window whose command was
still running at cleanup used to survive behind a terminate-processes sheet,
and across runs one host collected 241 of them; with that many, every command
inside Terminal timed out and the reset's own baseline probes failed. The home
restore never touched Terminal, so one bad run poisoned every later one.

So the reset asks Terminal to quit, kills the windows' processes and Terminal
itself when that quit hangs on a sheet, and relaunches Terminal without its
saved windows once the home is back.
"""

from __future__ import annotations

import shlex
from typing import Callable

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

from yoke_harness.ssh_mac_host_session_state import (
    TERMINAL_VISIBLE_WINDOW_COUNT,
    read_terminal_window_count,
)
from yoke_harness.ssh_mac_terminal_app import run_osascript
from yoke_harness.test_machine_types import HostActionResult

TERMINAL_APP = "Terminal"
QUIT_WAIT_SECONDS = 20
RELAUNCH_WAIT_SECONDS = 30
TERMINAL_PROBE_FAILED = "test_machine_terminal_probe_failed"
TERMINAL_QUIT_NOT_PROVED = "test_machine_terminal_quit_not_proved"
TERMINAL_RELAUNCH_FAILED = "test_machine_terminal_relaunch_failed"
# Launch without the saved windows: a relaunch that restored them would bring
# back the accumulation the quit just cleared.
RELAUNCH_COMMAND = "/usr/bin/open -a Terminal --args -ApplePersistenceIgnoreState YES"
_PGREP_NO_MATCH = 1
# The wait loop exits with this when pgrep itself failed rather than matched.
_WAIT_PROBE_FAILED = 3


def _running(user: str) -> str:
    return shlex.join(["/usr/bin/pgrep", "-x", "-u", user, TERMINAL_APP])


def _wait_exited(running: str) -> str:
    return (
        f"i=0; while [ $i -lt {QUIT_WAIT_SECONDS} ]; do "
        f"{running} >/dev/null; s=$?; [ $s -eq {_PGREP_NO_MATCH} ] && exit 0; "
        f"[ $s -ne 0 ] && exit {_WAIT_PROBE_FAILED}; "
        "/bin/sleep 1; i=$((i+1)); done; exit 1"
    )


def _force_kill(running: str) -> str:
    """Kill every process under each Terminal, deepest first, then Terminal."""
    return (
        'kill_tree() { for c in $(/usr/bin/pgrep -P "$1"); do kill_tree "$c"; '
        'done; /bin/kill -KILL "$1" 2>/dev/null; }; '
        f'for p in $({running}); do kill_tree "$p"; done; exit 0'
    )


def _wait_for_window() -> str:
    count = shlex.quote(TERMINAL_VISIBLE_WINDOW_COUNT)
    return (
        f"i=0; n=; while [ $i -lt {RELAUNCH_WAIT_SECONDS} ]; do "
        f"n=$(/usr/bin/osascript -e {count} 2>/dev/null); "
        '[ -n "$n" ] && [ "$n" -gt 0 ] && { echo "$n"; exit 0; }; '
        '/bin/sleep 1; i=$((i+1)); done; echo "${n:-none}"; exit 1'
    )


def _probe_failed(probe: str, result) -> HostActionResult:
    return HostActionResult(
        False,
        {
            "terminal_quit": {
                "probe": probe,
                "exit_code": int(result.returncode),
                "stderr": bounded_machine_qa_diagnostic(result.stderr),
            },
            "recovery": (
                "Yoke could not tell whether Terminal is running on the test "
                "machine. Check that SSH to the machine works (the stderr above "
                "names the failure), then retry the reset."
            ),
        },
        TERMINAL_PROBE_FAILED,
    )


def quit_terminal_app(run: Callable[..., object], user: str) -> HostActionResult:
    """Quit Terminal, forcing it when a sheet holds the quit, and prove it exited."""
    running = _running(user)
    probe = run(running + " >/dev/null")
    if probe.returncode == _PGREP_NO_MATCH:
        return HostActionResult(True, {"terminal_quit": {"quit": "not_running"}})
    if probe.returncode != 0:
        return _probe_failed("running", probe)
    evidence: dict[str, object] = {
        "windows_before_quit": read_terminal_window_count(run),
    }
    # A window still running a command answers quit with a sheet, so the
    # request is bounded rather than trusted to return.
    run_osascript(run, [f'tell application "{TERMINAL_APP}" to quit'], timeout=10)
    exited = run(_wait_exited(running), timeout=QUIT_WAIT_SECONDS + 15)
    if exited.returncode not in {0, 1}:
        return _probe_failed("exited", exited)
    evidence["quit"] = "graceful"
    if exited.returncode != 0:
        run(_force_kill(running), timeout=30)
        exited = run(_wait_exited(running), timeout=QUIT_WAIT_SECONDS + 15)
        if exited.returncode not in {0, 1}:
            return _probe_failed("exited", exited)
        evidence["quit"] = "forced"
    if exited.returncode != 0:
        return HostActionResult(
            False,
            {
                "terminal_quit": evidence,
                "recovery": (
                    "Terminal survived both its quit and a forced kill on the "
                    "test machine. Quit Terminal at the host console (Terminal "
                    "> Quit Terminal, then Terminate), then retry the reset."
                ),
            },
            TERMINAL_QUIT_NOT_PROVED,
        )
    return HostActionResult(True, {"terminal_quit": evidence})


def relaunch_terminal_app(run: Callable[..., object]) -> HostActionResult:
    """Start Terminal without its saved windows and wait for its first window."""
    launched = run(RELAUNCH_COMMAND, timeout=30)
    if launched.returncode == 0:
        opened = run(_wait_for_window(), timeout=RELAUNCH_WAIT_SECONDS + 15)
        windows = (opened.stdout or "").strip()
        if opened.returncode == 0 and windows.isdigit():
            return HostActionResult(
                True, {"terminal_relaunch": {"terminal_windows": int(windows)}}
            )
        detail = {"terminal_windows": windows or None, "wait": RELAUNCH_WAIT_SECONDS}
    else:
        detail = {
            "exit_code": int(launched.returncode),
            "stderr": bounded_machine_qa_diagnostic(launched.stderr),
        }
    return HostActionResult(
        False,
        {
            "terminal_relaunch": {"command": RELAUNCH_COMMAND, **detail},
            "recovery": (
                "The home was restored, but Terminal did not open a window on "
                "the test machine. Open Terminal at the host console, confirm "
                "a window appears, then run `yoke test-machine bridge-diagnose` "
                "before the next case."
            ),
        },
        TERMINAL_RELAUNCH_FAILED,
    )


__all__ = [
    "QUIT_WAIT_SECONDS",
    "RELAUNCH_COMMAND",
    "RELAUNCH_WAIT_SECONDS",
    "TERMINAL_PROBE_FAILED",
    "TERMINAL_QUIT_NOT_PROVED",
    "TERMINAL_RELAUNCH_FAILED",
    "quit_terminal_app",
    "relaunch_terminal_app",
]

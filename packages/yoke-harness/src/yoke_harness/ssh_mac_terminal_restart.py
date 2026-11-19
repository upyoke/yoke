"""Quit every app the test user left open for reset, then relaunch Terminal.

Every GUI-session command opens a Terminal window. A window whose command was
still running at cleanup used to survive behind a terminate-processes sheet,
and across runs one host collected 241 of them; with that many, every command
inside Terminal timed out and the reset's own baseline probes failed. Any other
app a run left open survived the same way: a Claude for Mac held open by a
sheet failed the next reset's desktop probe, and every reset after it.

So the reset asks each foreground app the sweep does not keep (Terminal among
them) and System Events to quit, kills a stalled app's process tree when that
quit hangs on a sheet, and relaunches Terminal without its saved windows once
the home is back.
"""

from __future__ import annotations

import shlex
from typing import Callable

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

from yoke_harness.ssh_mac_gui_app_sweep import (
    TERMINAL_BUNDLE_ID,
    list_foreground_apps,
    running_pid,
)
from yoke_harness.ssh_mac_process_tree import PROCESS_TREE_FUNCTION
from yoke_harness.ssh_mac_host_session_state import (
    TERMINAL_VISIBLE_WINDOW_COUNT,
    read_console_user,
    read_terminal_window_count,
)
from yoke_harness.ssh_mac_terminal_app import run_osascript
from yoke_contracts.test_machine_types import HostActionResult

QUIT_WAIT_SECONDS = 20
RELAUNCH_WAIT_SECONDS = 30
GUI_APP_PROBE_FAILED = "test_machine_gui_app_probe_failed"
GUI_APP_QUIT_NOT_PROVED = "test_machine_gui_app_quit_not_proved"
RESET_CONSOLE_USER_MISMATCH = "test_machine_reset_console_user_mismatch"
TERMINAL_RELAUNCH_FAILED = "test_machine_terminal_relaunch_failed"
# Launch without the saved windows: a relaunch that restored them would bring
# back the accumulation the quit just cleared.
RELAUNCH_COMMAND = "/usr/bin/open -a Terminal --args -ApplePersistenceIgnoreState YES"
_PGREP_NO_MATCH = 1
# The wait loop exits with this when pgrep itself failed rather than matched.
_WAIT_PROBE_FAILED = 3


def _running(user: str, app: str) -> str:
    return shlex.join(["/usr/bin/pgrep", "-x", "-u", user, app])


def _wait_exited(running: str) -> str:
    return (
        f"i=0; while [ $i -lt {QUIT_WAIT_SECONDS} ]; do "
        f"{running} >/dev/null; s=$?; [ $s -eq {_PGREP_NO_MATCH} ] && exit 0; "
        f"[ $s -ne 0 ] && exit {_WAIT_PROBE_FAILED}; "
        "/bin/sleep 1; i=$((i+1)); done; exit 1"
    )


def _force_kill(running: str) -> str:
    """Kill each app's descendants and then the app under POSIX word splitting."""
    script = (
        f"{PROCESS_TREE_FUNCTION}; for p in $({running}); do "
        '/bin/kill -KILL $(process_tree "$p") 2>/dev/null; done; exit 0'
    )
    return shlex.join(("/bin/sh", "-c", script))


def _wait_for_window() -> str:
    count = shlex.quote(TERMINAL_VISIBLE_WINDOW_COUNT)
    return (
        f"i=0; n=; while [ $i -lt {RELAUNCH_WAIT_SECONDS} ]; do "
        f"n=$(printf '%s\\n' {count} | /usr/bin/osascript 2>/dev/null); "
        '[ -n "$n" ] && [ "$n" -gt 0 ] && { echo "$n"; exit 0; }; '
        '/bin/sleep 1; i=$((i+1)); done; echo "${n:-none}"; exit 1'
    )


def _probe_failed(probe: str, result, app: str, key: str) -> HostActionResult:
    return HostActionResult(
        False,
        {
            key: {
                "probe": probe,
                "exit_code": int(result.returncode),
                "stderr": bounded_machine_qa_diagnostic(result.stderr),
            },
            "recovery": (
                f"Yoke could not tell whether {app} is running on the test "
                "machine. Check that SSH to the machine works (the stderr above "
                "names the failure), then retry the reset."
            ),
        },
        f"test_machine_{key.removesuffix('_quit')}_probe_failed",
    )


def _quit_app(
    run: Callable[..., object],
    running: str,
    app: str,
    target: str,
    key: str,
    *,
    count_windows: bool = False,
) -> HostActionResult:
    """Ask the app to quit, force a stalled tree, and prove it exited.

    *running* prints the app's PIDs, exiting 1 once none run and above 1 when
    it cannot tell; *target* is the AppleScript application to quit.
    """
    probe = run(running + " >/dev/null")
    if probe.returncode == _PGREP_NO_MATCH:
        return HostActionResult(True, {key: {"quit": "not_running"}})
    if probe.returncode != 0:
        return _probe_failed("running", probe, app, key)
    evidence: dict[str, object] = {}
    if count_windows:
        evidence["windows_before_quit"] = read_terminal_window_count(run)
    # A window still running a command answers quit with a sheet, so the
    # request is bounded rather than trusted to return.
    run_osascript(run, [f"tell {target} to quit"], timeout=10)
    exited = run(_wait_exited(running), timeout=QUIT_WAIT_SECONDS + 15)
    if exited.returncode not in {0, 1}:
        return _probe_failed("exited", exited, app, key)
    evidence["quit"] = "graceful"
    if exited.returncode != 0:
        run(_force_kill(running), timeout=30)
        exited = run(_wait_exited(running), timeout=QUIT_WAIT_SECONDS + 15)
        if exited.returncode not in {0, 1}:
            return _probe_failed("exited", exited, app, key)
        evidence["quit"] = "forced"
    if exited.returncode != 0:
        return HostActionResult(
            False,
            {
                key: evidence,
                "recovery": (
                    f"{app} survived both its quit and a forced kill on the "
                    f"test machine. Quit {app} at the host console using "
                    "Activity Monitor, then retry the reset."
                ),
            },
            f"test_machine_{key}_not_proved",
        )
    return HostActionResult(True, {key: evidence})


def _console_user_mismatch(console_user: str | None, user: str) -> HostActionResult:
    return HostActionResult(
        False,
        {
            "console_user": console_user,
            "expected_console_user": user,
            "recovery": (
                f"The test machine's console is logged in as {console_user or 'nobody'}, "
                f"not {user}, so the reset quit no app. Log {user} in at the "
                "host console (log any other account out), then retry the reset."
            ),
        },
        RESET_CONSOLE_USER_MISMATCH,
    )


def quit_reset_apps(run: Callable[..., object], user: str) -> HostActionResult:
    """Quit every foreground app not kept, then System Events, before restore."""
    console_user = read_console_user(run)
    if console_user != user:
        return _console_user_mismatch(console_user, user)
    listed = list_foreground_apps(run, user)
    if isinstance(listed, HostActionResult):
        return listed
    apps, kept = listed
    evidence: dict[str, object] = {"gui_apps_kept": kept, "gui_apps_quit": []}
    for app in apps:
        quit = _quit_app(
            run,
            running_pid(user, app.pid),
            app.name,
            app.target,
            "gui_app_quit",
            count_windows=app.bundle_id == TERMINAL_BUNDLE_ID,
        )
        entry = {"app": app.name, "bundle_id": app.bundle_id, "pid": app.pid}
        evidence["gui_apps_quit"].append({**entry, **quit.evidence["gui_app_quit"]})
        if not quit.ok:
            evidence["recovery"] = quit.evidence["recovery"]
            return HostActionResult(False, evidence, quit.error_code)
    events = _quit_app(
        run,
        _running(user, "System Events"),
        "System Events",
        'application "System Events"',
        "system_events_quit",
    )
    return HostActionResult(events.ok, {**evidence, **events.evidence}, events.error_code)


def relaunch_terminal_app(run: Callable[..., object]) -> HostActionResult:
    """Start Terminal without its saved windows and wait for its first window."""
    launched = run(RELAUNCH_COMMAND, timeout=30)
    if launched.returncode == 0:
        opened = run(
            "/bin/sh -s",
            input_text=_wait_for_window(),
            timeout=RELAUNCH_WAIT_SECONDS + 15,
        )
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
    "GUI_APP_PROBE_FAILED",
    "GUI_APP_QUIT_NOT_PROVED",
    "QUIT_WAIT_SECONDS",
    "RELAUNCH_COMMAND",
    "RELAUNCH_WAIT_SECONDS",
    "RESET_CONSOLE_USER_MISMATCH",
    "TERMINAL_RELAUNCH_FAILED",
    "quit_reset_apps",
    "relaunch_terminal_app",
]

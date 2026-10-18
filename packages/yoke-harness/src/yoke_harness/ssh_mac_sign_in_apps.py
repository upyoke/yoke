"""Quit the macOS apps holding sign-ins before a capture or reset touches them.

Safari writes its cookie store when it quits. A store copied or kept while
Safari runs can miss the newest sign-in, and Safari later writes its in-memory
state back over a home restored under it. Capture and reset therefore quit it
first, gracefully: a forced kill would discard the cookies being saved.

Only pgrep's own "no match" exit (1) means an app is not running. Any other
exit, such as an SSH or runner failure, proves nothing about the app.
"""

from __future__ import annotations

import shlex
from typing import Callable

from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic

from yoke_harness.ssh_mac_terminal_app import run_osascript
from yoke_harness.test_machine_types import HostActionResult

SIGN_IN_APPS = ("Safari",)
QUIT_WAIT_SECONDS = 30
SIGN_IN_APP_QUIT_NOT_PROVED = "test_machine_sign_in_app_quit_not_proved"
SIGN_IN_APP_PROBE_FAILED = "test_machine_sign_in_app_probe_failed"
_PGREP_NO_MATCH = 1
# The wait loop exits with this when pgrep itself failed rather than matched.
_WAIT_PROBE_FAILED = 3


def _probe_failed(app: str, probe: str, result) -> HostActionResult:
    return HostActionResult(
        False,
        {
            "app": app,
            "probe": probe,
            "exit_code": int(result.returncode),
            "stderr": bounded_machine_qa_diagnostic(result.stderr),
            "recovery": (
                f"Yoke could not tell whether {app} is running on the test "
                "machine. Check that SSH to the machine works (the stderr above "
                "names the failure), then retry."
            ),
        },
        SIGN_IN_APP_PROBE_FAILED,
    )


def quit_sign_in_apps(run: Callable[..., object], user: str) -> HostActionResult:
    """Ask each running sign-in app to quit and prove it exited."""
    quit_apps: list[str] = []
    for app in SIGN_IN_APPS:
        running = shlex.join(["/usr/bin/pgrep", "-x", "-u", user, app])
        probe = run(running + " >/dev/null")
        if probe.returncode == _PGREP_NO_MATCH:
            continue
        if probe.returncode != 0:
            return _probe_failed(app, "running", probe)
        asked = run_osascript(run, [f'tell application "{app}" to quit'])
        exited = run(
            f"i=0; while [ $i -lt {QUIT_WAIT_SECONDS} ]; do "
            f"{running} >/dev/null; s=$?; [ $s -eq {_PGREP_NO_MATCH} ] && exit 0; "
            f"[ $s -ne 0 ] && exit {_WAIT_PROBE_FAILED}; "
            "/bin/sleep 1; i=$((i+1)); done; exit 1",
            timeout=QUIT_WAIT_SECONDS + 15,
        )
        if exited.returncode not in {0, 1}:
            return _probe_failed(app, "exited", exited)
        if exited.returncode != 0:
            return HostActionResult(
                False,
                {
                    "app": app,
                    "quit_requested": asked.returncode == 0,
                    "recovery": (
                        f"Quit {app} on the test machine ({app} > Quit {app}), "
                        "answering any prompt it shows, then retry. It was not "
                        "force-quit, so its unsaved sign-ins are still in memory."
                        + (
                            ""
                            if asked.returncode == 0
                            else f" To let Yoke quit it next time, allow the SSH "
                            f"session to control {app} in System Settings > "
                            "Privacy & Security > Automation."
                        )
                    ),
                },
                SIGN_IN_APP_QUIT_NOT_PROVED,
            )
        quit_apps.append(app)
    return HostActionResult(True, {"sign_in_apps_quit": quit_apps})


__all__ = [
    "QUIT_WAIT_SECONDS",
    "SIGN_IN_APP_PROBE_FAILED",
    "SIGN_IN_APPS",
    "SIGN_IN_APP_QUIT_NOT_PROVED",
    "quit_sign_in_apps",
]

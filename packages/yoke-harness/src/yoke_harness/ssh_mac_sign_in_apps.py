"""Close the macOS identity browsers before a capture or reset touches them.

The identity profiles are the test machine's only login store. Chromium writes
a profile's cookie store as it shuts down, so a store kept while it runs can
miss the newest sign-in, and a running browser writes its in-memory state back
over a home restored under it. Capture and reset therefore ask every identity
browser's main process to quit with SIGTERM, which Chromium handles as a clean
shutdown, and prove it exited. A forced kill would discard the cookies being
saved. The probe uses only guaranteed macOS primitives (ps, awk, kill).
"""

from __future__ import annotations

import shlex
from typing import Callable

from yoke_contracts.browser_identity import LIVE_IDENTITY_STORE_HOME_ENTRY
from yoke_contracts.machine_qa_failures import bounded_machine_qa_diagnostic
from yoke_contracts.test_machine_types import HostActionResult

QUIT_WAIT_SECONDS = 30
SIGN_IN_APP_QUIT_NOT_PROVED = "test_machine_sign_in_app_quit_not_proved"
SIGN_IN_APP_PROBE_FAILED = "test_machine_sign_in_app_probe_failed"
IDENTITY_BROWSER = "identity browser"
_NONE_RUNNING = 10
_STILL_RUNNING = 11


def _close_script(user: str) -> str:
    """Exit 0 closed, 10 none running, 11 still running, other probe failure.

    The flag is assembled inside awk, so no probe's own command line carries
    the full ``--user-data-dir=<store>`` text it looks for.
    """
    return (
        f'store="$HOME/{LIVE_IDENTITY_STORE_HOME_ENTRY}/"; '
        "browsers() { /bin/ps -U " + shlex.quote(user) + " -o pid=,command= | "
        "/usr/bin/awk -v s=\"$store\" 'BEGIN { m = \"--user-data\" \"-dir=\" s } "
        "index($0, m) && !index($0, \"--type=\") {print $1}'; }; "
        "pids=$(browsers) || exit 3; "
        f"[ -z \"$pids\" ] && exit {_NONE_RUNNING}; "
        "/bin/kill -TERM $pids 2>/dev/null; "
        f"i=0; while [ $i -lt {QUIT_WAIT_SECONDS} ]; do "
        "left=$(browsers) || exit 3; [ -z \"$left\" ] && exit 0; "
        "/bin/sleep 1; i=$((i+1)); done; "
        f"exit {_STILL_RUNNING}"
    )


def quit_sign_in_apps(run: Callable[..., object], user: str) -> HostActionResult:
    """Ask each running identity browser to quit and prove it exited."""
    result = run(_close_script(user), timeout=QUIT_WAIT_SECONDS + 15)
    code = int(result.returncode)
    if code in (0, _NONE_RUNNING):
        return HostActionResult(
            True, {"sign_in_apps_quit": [IDENTITY_BROWSER] if code == 0 else []}
        )
    if code == _STILL_RUNNING:
        return HostActionResult(
            False,
            {
                "app": IDENTITY_BROWSER,
                "recovery": (
                    "Close every identity browser window on the test machine, "
                    "answering any prompt it shows, then retry. It was not "
                    "force-quit, so its unsaved sign-ins are still in memory."
                ),
            },
            SIGN_IN_APP_QUIT_NOT_PROVED,
        )
    return HostActionResult(
        False,
        {
            "app": IDENTITY_BROWSER,
            "exit_code": code,
            "stderr": bounded_machine_qa_diagnostic(getattr(result, "stderr", "")),
            "recovery": (
                "Yoke could not tell whether an identity browser is running on "
                "the test machine. Check that SSH to the machine works (the "
                "stderr above names the failure), then retry."
            ),
        },
        SIGN_IN_APP_PROBE_FAILED,
    )


__all__ = [
    "QUIT_WAIT_SECONDS",
    "SIGN_IN_APP_PROBE_FAILED",
    "SIGN_IN_APP_QUIT_NOT_PROVED",
    "quit_sign_in_apps",
]

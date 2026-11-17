"""Quit every Chromium the Linux test user runs; shipped after linux_chromium_processes.

Chromium writes its cookie store when it quits, so a capture or reset first
asks it to quit, never kills it. No __future__ import: the host runs this as
a stdlib program.
"""

import json
import sys

from yoke_harness import linux_chromium_processes as native_processes

QUIT_WAIT_SECONDS = 30
POLL_SECONDS = 0.25


def quit_chromium():
    return native_processes.quit_processes(
        native_processes.browser_pids, QUIT_WAIT_SECONDS, POLL_SECONDS
    )


def main():
    command = sys.argv[1]
    try:
        if command != "quit":
            raise native_processes.ChromiumRefusal(
                "linux_desktop_chromium_command_unknown", "Use a registered command."
            )
        result = {"quit": quit_chromium()}
    except native_processes.ChromiumRefusal as refusal:
        print(json.dumps({"ok": False, "reason": refusal.reason, "recovery": refusal.recovery}))
        raise SystemExit(69)
    print(json.dumps({"ok": True, **result}))

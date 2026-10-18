"""Discover and gracefully stop only the native Chromium main processes."""

import os
from pathlib import Path
import signal
import time


class ChromiumRefusal(RuntimeError):
    def __init__(self, reason, recovery):
        super().__init__(reason)
        self.reason, self.recovery = reason, recovery


def browser_pids():
    pids = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            if Path(os.readlink(process / "exe")).name not in {
                "chrome",
                "chromium",
                "chromium-browser",
            }:
                continue
            # Chromium's process title can flatten all argv into one NUL field.
            argv = (process / "cmdline").read_bytes().replace(b"\0", b" ").split()
        except OSError:
            continue
        if not any(arg.startswith(b"--type=") for arg in argv):
            pids.append(int(process.name))
    return pids


def quit_processes(discover, timeout, poll):
    pids = discover()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while discover():
        if time.monotonic() >= deadline:
            raise ChromiumRefusal(
                "linux_desktop_chromium_quit_not_proved",
                "Close every Chromium window on the test machine's desktop, answering any prompt it shows, then retry. Chromium was asked to quit and was not force-killed, so its unsaved sign-ins are still in memory.",
            )
        time.sleep(poll)
    return bool(pids)

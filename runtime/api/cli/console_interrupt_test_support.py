"""Deliver a real Ctrl-C to a spawned process on POSIX and Windows.

POSIX delivers SIGINT with ``os.kill``. On Windows ``os.kill(pid, SIGINT)``
is TerminateProcess, so the child never sees an interrupt. A Windows Ctrl-C
is a console event: spawn the target in its own console, then a helper
attaches to that console and raises CTRL_C_EVENT for every process in it,
exactly as a keypress in that window would.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

_WINDOWS_CTRL_C = """
import ctypes, sys
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.FreeConsole()
if not kernel32.AttachConsole(int(sys.argv[1])):
    raise SystemExit(f"attach_console_failed: error {ctypes.get_last_error()}")
kernel32.SetConsoleCtrlHandler(None, True)
if not kernel32.GenerateConsoleCtrlEvent(0, 0):
    raise SystemExit(f"ctrl_c_event_failed: error {ctypes.get_last_error()}")
"""


def interruptible_popen_kwargs() -> dict:
    """Popen options that let ``send_console_interrupt`` reach the child."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_CONSOLE}
    return {}


def send_console_interrupt(pid: int) -> None:
    """Interrupt *pid* (started with ``interruptible_popen_kwargs``) like Ctrl-C."""
    if os.name != "nt":
        os.kill(pid, signal.SIGINT)
        return
    subprocess.run(
        [sys.executable, "-c", _WINDOWS_CTRL_C, str(pid)],
        check=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

"""The generated ``task-runner.py`` the Windows relay task runs, windowless.

The task starts the venv's ``pythonw.exe``, so neither the runner nor the
relay owns a console window. ``pythonw`` gives the runner no stdio: its own
messages and any crash go to the relay's stderr log. It starts the relay with
``CREATE_NO_WINDOW`` so the console child opens no window either, and it
restarts the relay on every exit, backing off after quick failures, until the
task is ended. Task Scheduler's RestartOnFailure only covers a task that fails
to launch; an action that exits counts as a finished run, so a relay that
died was not restarted before the next logon.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from yoke_contracts.machine_config.relay_instance import WINDOWS_RELAY_RESTART_CODE

#: Win32 CREATE_NO_WINDOW: the console child gets a console with no window.
CREATE_NO_WINDOW = 0x08000000
#: A relay that ran this long before exiting restarts at the shortest delay.
RELAY_HEALTHY_RUN_SECONDS = 300
#: Longest wait before restarting a relay that keeps exiting quickly.
RELAY_RESTART_MAX_DELAY_SECONDS = 60

#: Task Scheduler's End stops only the task's own process, so the runner joins
#: a kill-on-close job first: ending or deleting the task then also stops the
#: relay it started, as systemd stops a unit's whole control group on Linux.
#: Only a child that asks to break away leaves it: the uninstall finisher must
#: outlive the task that uninstall deletes.
CONTAIN_RUNNER = """\
if globals().get("__name__") == "__main__":
    import ctypes
    from ctypes import wintypes
    class _Basic(ctypes.Structure):
        _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("flags", wintypes.DWORD),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD),
                    ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
    class _Extended(ctypes.Structure):
        _fields_ = [("basic", _Basic), ("io", ctypes.c_uint64 * 6),
                    ("limits", ctypes.c_size_t * 4)]
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _k.CreateJobObjectW.restype = wintypes.HANDLE
    _k.GetCurrentProcess.restype = wintypes.HANDLE
    _k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _job = _k.CreateJobObjectW(None, None)
    _info = _Extended()
    _info.basic.flags = 0x2000 | 0x800  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK
    if not (_job and _k.SetInformationJobObject(_job, 9, ctypes.byref(_info), ctypes.sizeof(_info))
            and _k.AssignProcessToJobObject(_job, _k.GetCurrentProcess())):
        raise SystemExit(f"relay_task_containment_failed: {ctypes.WinError(ctypes.get_last_error())}; "
                         "retry `yoke relay install`")
"""


def relay_task_runner_source(
    *,
    environment: Mapping[str, str],
    argv: Sequence[str],
    stdout_log: Path,
    stderr_log: Path,
    contain: bool,
) -> str:
    """The runner source; its environment and relay argv stay literals.

    Uninstall and the orphan scan read both literals back as data.
    """
    flags = f"{CREATE_NO_WINDOW:#x} if os.name == 'nt' else 0"
    return (
        "import os, subprocess, sys, time\n"
        "if sys.stderr is None:\n"
        "    # pythonw has no stdio: runner messages and crashes go to the stderr log.\n"
        f"    sys.stdout = sys.stderr = open({str(stderr_log)!r}, 'a', encoding='utf-8', buffering=1)\n"
        + (CONTAIN_RUNNER if contain else "")
        + f"os.environ.update({dict(environment)!r})\n"
        "failures = 0\n"
        f"with open({str(stdout_log)!r}, 'ab', buffering=0) as out, "
        f"open({str(stderr_log)!r}, 'ab', buffering=0) as err:\n"
        "    while True:\n"
        "        started = time.monotonic()\n"
        f"        code = subprocess.call({list(argv)!r}, stdin=subprocess.DEVNULL, "
        f"stdout=out, stderr=err, creationflags={flags})\n"
        f"        if code == {WINDOWS_RELAY_RESTART_CODE}:\n"
        "            failures = 0\n"
        "            continue\n"
        f"        failures = 0 if time.monotonic() - started >= {RELAY_HEALTHY_RUN_SECONDS} else failures + 1\n"
        f"        delay = min({RELAY_RESTART_MAX_DELAY_SECONDS}, 2 ** min(failures, 6))\n"
        "        print(time.strftime('%Y-%m-%dT%H:%M:%S'), f'relay_exited_unexpectedly: exit {code}; '\n"
        "              f'the task runner restarts it in {delay}s', file=sys.stderr, flush=True)\n"
        "        time.sleep(delay)\n"
    )


__all__ = [
    "CONTAIN_RUNNER",
    "CREATE_NO_WINDOW",
    "RELAY_HEALTHY_RUN_SECONDS",
    "RELAY_RESTART_MAX_DELAY_SECONDS",
    "relay_task_runner_source",
]

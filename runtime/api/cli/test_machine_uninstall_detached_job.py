"""The final CLI removal survives the kill-on-close job of a Windows SSH session."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.windows,
    pytest.mark.windows_only(reason="Win32 job objects"),
]

KILL_ON_JOB_CLOSE = 0x2000
BREAKAWAY_OK = 0x800

# The parent's job handle closes when it exits, as sshd's does with the session.
PARENT = """\
import ctypes, json, sys
from ctypes import wintypes
from pathlib import Path
class Basic(ctypes.Structure):
    _fields_ = [("a", ctypes.c_int64), ("b", ctypes.c_int64), ("flags", wintypes.DWORD),
                ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", wintypes.DWORD),
                ("f", ctypes.c_size_t), ("g", wintypes.DWORD), ("h", wintypes.DWORD)]
class Extended(ctypes.Structure):
    _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("limits", ctypes.c_size_t * 4)]
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateJobObjectW.restype = wintypes.HANDLE
k.GetCurrentProcess.restype = wintypes.HANDLE
k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
job = k.CreateJobObjectW(None, None)
info = Extended()
info.basic.flags = int(sys.argv[2])
if not (job and k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        and k.AssignProcessToJobObject(job, k.GetCurrentProcess())):
    raise SystemExit(f"job setup failed: {ctypes.WinError(ctypes.get_last_error())}")
from yoke_cli.config.machine_uninstall_detached import prepare
try:
    handoff = prepare(Path(sys.argv[1]))
except RuntimeError as exc:
    print(json.dumps({"refused": str(exc)}), flush=True)
    raise SystemExit(0)
handoff.arm()
print(json.dumps({"log": str(handoff.log)}), flush=True)
"""


@pytest.fixture
def install(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    root = tmp_path / "tools" / "yoke-cli-releases"
    generation = root / "releases" / "1.0"
    generation.mkdir(parents=True)
    (generation / "lease").touch()
    (root / "current").write_text("1.0\n")
    (root / "launcher").touch()
    shim = bin_dir / "yoke.cmd"
    shim.write_text(f'@echo off\r\npython "{root / "launcher"}" %*\r\n')
    (bin_dir / "uv.cmd").write_text(
        '@echo off\r\nif "%3"=="--bin" goto bin\r\n'
        f"echo {root.parent}\r\nexit /b 0\r\n:bin\r\necho {bin_dir}\r\n"
    )
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(temp))
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "profile"))
    return root, shim, tmp_path / "machine"


def _run_parent(machine_home: Path, flags: int) -> dict:
    result = subprocess.run(
        [sys.executable, "-c", PARENT, str(machine_home), str(flags)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_finisher_breaks_away_and_removes_the_release(install):
    root, shim, machine_home = install
    report = _run_parent(machine_home, KILL_ON_JOB_CLOSE | BREAKAWAY_OK)
    log = Path(report["log"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and log.parent.exists():
        time.sleep(0.05)
    assert not log.parent.exists(), log.read_text() if log.exists() else "no log"
    assert not root.exists()
    assert not shim.exists()


def test_job_that_forbids_breakaway_refuses_and_keeps_the_release(install):
    root, shim, machine_home = install
    report = _run_parent(machine_home, KILL_ON_JOB_CLOSE)
    assert "uninstall_cli_handoff_failed" in report["refused"]
    assert "forbids breakaway" in report["refused"]
    assert (root / "releases" / "1.0" / "lease").is_file()
    assert shim.is_file()

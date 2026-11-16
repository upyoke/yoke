"""Release runtime facts that differ by OS: launcher death, leases, shims.

Real-process tests run on the OS they name; fake Windows facts run everywhere.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from runtime.api.cli.cli_release_runtime_test_support import candidate, point_current
from yoke_cli.config import cli_release_runtime as runtime


pytestmark = pytest.mark.windows

POSIX_ONLY = pytest.mark.skipif(runtime.WINDOWS, reason="POSIX process facts")


def _alive(pid: int) -> bool:
    if runtime.WINDOWS:
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        )
        return str(pid) in listing.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


STOPS = ["kill"] if runtime.WINDOWS else ["kill", signal.SIGTERM]


@pytest.mark.parametrize("stop", STOPS)
def test_stopping_the_launcher_ends_its_command(tmp_path, stop):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    runtime.activate(root, candidate(root, "1.0"), bin_dir, "1.0")
    # Start the launcher itself, as the shims do, so stopping it is direct.
    launcher = subprocess.Popen(
        [sys.executable, str(root / "launcher"), "hold"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        command = int(launcher.stdout.readline())
        launcher.kill() if stop == "kill" else launcher.send_signal(stop)
        launcher.wait(timeout=10)
        deadline = time.monotonic() + 10
        while _alive(command) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(command), "the command outlived its launcher"
    finally:
        launcher.kill()
        launcher.communicate()


@POSIX_ONLY
def test_symlinked_tool_root_retains_current_and_uninstalls(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    active = candidate(root, "1.0")
    alias = tmp_path / "tool-link"
    alias.symlink_to(root, target_is_directory=True)
    runtime.activate(alias, alias / "releases/1.0", bin_dir, "1.0")
    with runtime.locked(root / "publication.lock"):
        runtime.collect(alias)
    assert active.exists()
    runtime.uninstall(alias, bin_dir)
    assert not root.exists()


@POSIX_ONLY
def test_resident_exec_keeps_the_new_release_leased(tmp_path, monkeypatch):
    import fcntl

    root = tmp_path / "runtime"
    old, new = root / "releases/old", root / "releases/new"
    for generation in (old, new):
        runtime.release_python(generation).parent.mkdir(parents=True)
        (generation / "lease").touch()
    point_current(root, new)
    monkeypatch.setattr(sys, "executable", str(runtime.release_python(old)))
    calls = []

    def replace(python, arguments):
        with (new / "lease").open("a+") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not runtime._retire(new, root / "retired"), "cleanup took it"
        lease = (new / "lease").stat().st_ino
        assert any(_inheritable(fd, lease) for fd in range(3, 1024)), (
            "the lease must survive the exec"
        )
        calls.append((python, arguments))

    monkeypatch.setattr(os, "execv", replace)
    assert runtime.exec_current_python(["-m", "yoke_harness.hook_resident"]) == 0
    python = str(runtime.release_python(new))
    assert calls == [(python, [python, "-m", "yoke_harness.hook_resident"])]


def _inheritable(fd: int, inode: int) -> bool:
    try:
        return os.fstat(fd).st_ino == inode and os.get_inheritable(fd)
    except OSError:
        return False


def test_windows_layout_uses_scripts_python_and_cmd_shim(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    generation = tmp_path / "releases/1.0"
    assert runtime.release_python(generation) == (
        generation / "tools/yoke-cli/Scripts/python.exe"
    )
    python, root = Path("C:/Python/python.exe"), tmp_path / "root"
    shims = runtime._shims(root, python, tmp_path / "bin")
    assert shims[tmp_path / "bin/yoke.cmd"] == (
        f'@"{python}" "{root / "launcher"}" %*\r\n'
    )
    # Git Bash runs the extensionless shim; Git runs helpers through sh too.
    assert shims[tmp_path / "bin/yoke"].startswith("#!/bin/sh\nexec ")
    assert shims[root / "python"].endswith(' --python "$@"\n')
    with pytest.raises(RuntimeError, match="cli_launcher_path_unsupported"):
        runtime._shims(tmp_path / "100%", python, tmp_path / "bin")


def test_windows_cleanup_skips_a_release_whose_rename_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    release = tmp_path / "releases/1.0"
    release.mkdir(parents=True)

    def refuse(self, target):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(Path, "rename", refuse)
    assert not runtime._retire(release, tmp_path / "retired")
    assert release.is_dir()


def test_windows_pointer_replace_retries_a_briefly_open_reader(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    replace, attempts = os.replace, []

    def busy_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            raise PermissionError(5, "Access is denied")
        replace(source, target)

    monkeypatch.setattr(runtime.os, "replace", busy_once)
    runtime._replace(tmp_path / "current", "2.0\n")
    assert (tmp_path / "current").read_text() == "2.0\n"
    assert len(attempts) == 2


def test_current_must_name_a_release_folder(tmp_path):
    for name in ("", "..", "../elsewhere", ".retired"):
        (tmp_path / "current").write_text(name + "\n")
        with pytest.raises(RuntimeError, match="cli_release_target_invalid"):
            runtime._generation(tmp_path)

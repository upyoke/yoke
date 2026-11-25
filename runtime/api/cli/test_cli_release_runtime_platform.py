"""Release runtime facts that differ by OS: launcher death, leases, shims.

Real-process tests run on the OS they name; fake Windows facts run everywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from runtime.api.cli.cli_release_runtime_test_support import candidate, point_current, yoke
from yoke_cli.config import cli_release_runtime as runtime


POSIX_ONLY = pytest.mark.posix_only(reason='POSIX process facts')


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


@pytest.mark.windows
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
def test_posix_shim_passes_the_restart_code_and_retires_the_old_release(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    new = candidate(root, "2.0")

    with subprocess.Popen(
        [yoke(bin_dir), "exit-on-publication"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as command:
        try:
            assert command.stdout.readline() == "ready\n"
            point_current(root, new)
            command.communicate(input="continue\n", timeout=10)
            assert command.returncode == 75
        finally:
            if command.poll() is None:
                command.kill()
    assert not old.exists()
    assert new.is_dir()


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


@pytest.mark.windows
def test_windows_layout_uses_scripts_python_and_cmd_shim(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    generation = tmp_path / "releases/1.0"
    assert runtime.release_python(generation) == (
        generation / "tools/yoke-cli/Scripts/python.exe"
    )
    python, root = Path("C:/Python/python.exe"), tmp_path / "root"
    shims = runtime._shims(root, python, tmp_path / "bin")
    assert shims[tmp_path / "bin/yoke.cmd"] == (
        f'@(goto) 2>nul & "{python}" -I -S "{root / "launcher"}" %*\r\n'
    )
    # Git Bash runs the extensionless shim; Git runs helpers through sh too.
    # The stdlib-only launcher skips site and user paths on every shim.
    assert shims[tmp_path / "bin/yoke"].startswith(
        f"#!/bin/sh\nexec {python.as_posix()} -I -S "
    )
    assert shims[root / "python"].endswith(' --python "$@"\n')
    with pytest.raises(RuntimeError, match="cli_launcher_path_unsupported"):
        runtime._shims(tmp_path / "100%", python, tmp_path / "bin")


@pytest.mark.windows
@pytest.mark.windows_only(reason="cmd.exe runs the yoke.cmd shim")
@pytest.mark.parametrize("code", [0, 1, 7, 75])
def test_cmd_shim_exits_with_the_command_code_and_keeps_arguments(tmp_path, code):
    root, bin_dir = tmp_path / "root", tmp_path / "bin"
    root.mkdir()
    (root / "launcher").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(int(sys.argv[1]))\n"
    )
    shim = runtime._shims(root, Path(sys.executable), bin_dir)[bin_dir / "yoke.cmd"]
    bin_dir.mkdir()
    (bin_dir / "yoke.cmd").write_bytes(shim.encode())
    arguments = [str(code), "two words", 'say "hi"', "a & b"]
    result = subprocess.run(
        [str(bin_dir / "yoke.cmd"), *arguments], capture_output=True, text=True
    )
    assert (result.returncode, json.loads(result.stdout)) == (code, arguments)
    caller = tmp_path / "caller.cmd"  # %ERRORLEVEL% as a batch caller reads it
    caller.write_bytes(f'@call "{bin_dir / "yoke.cmd"}" {code} >nul\r\n@exit /b %ERRORLEVEL%\r\n'.encode())
    assert subprocess.run([str(caller)]).returncode == code


@pytest.mark.windows
@pytest.mark.windows_only(reason="cmd.exe must finish after the batch file is deleted")
@pytest.mark.parametrize("entry", ["yoke.cmd", "caller.cmd"])
@pytest.mark.parametrize("code", [0, 7])
def test_cmd_shim_can_disappear_while_the_command_runs(tmp_path, entry, code):
    bin_dir = tmp_path / "bin with spaces"
    bin_dir.mkdir()
    (bin_dir / "launcher").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "Path(__file__).with_name('yoke.cmd').unlink()\n"
        "print(json.dumps([str(Path.cwd()), *sys.argv[1:]]))\n"
        "sys.exit(int(sys.argv[1]))\n"
    )
    shim = bin_dir / "yoke.cmd"
    shim.write_bytes(runtime._shims(bin_dir, Path(sys.executable), bin_dir)[shim].encode())
    (tmp_path / "caller.cmd").write_bytes(
        b'@call yoke.cmd %*\r\n@echo caller_after=%ERRORLEVEL%\r\n@exit /b %ERRORLEVEL%\r\n'
    )
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}

    result = subprocess.run(
        f'cmd.exe /d /c {entry} {code} plain "two words"',
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10,
    )

    assert result.returncode == code
    assert result.stderr == ""
    child, *after = result.stdout.splitlines()
    cwd, *arguments = json.loads(child)
    assert Path(cwd) == tmp_path
    assert arguments == [str(code), "plain", "two words"]
    assert after == ([f"caller_after={code}"] if entry == "caller.cmd" else [])
    assert not shim.exists()


@pytest.mark.windows
def test_windows_cleanup_skips_a_release_whose_rename_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    release = tmp_path / "releases/1.0"
    release.mkdir(parents=True)

    def refuse(self, target):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(Path, "rename", refuse)
    assert not runtime._retire(release, tmp_path / "retired")
    assert release.is_dir()


@pytest.mark.windows
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


@pytest.mark.windows
def test_current_must_name_a_release_folder(tmp_path):
    for name in ("", "..", "../elsewhere", ".retired"):
        (tmp_path / "current").write_text(name + "\n")
        with pytest.raises(RuntimeError, match="cli_release_target_invalid"):
            runtime._generation(tmp_path)


@pytest.mark.windows
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:\\Users\\me\\uv\\tools\\yoke-cli-releases", "\\\\?\\C:\\Users\\me\\uv\\tools\\yoke-cli-releases"),
        ("\\\\?\\C:\\already\\long", "\\\\?\\C:\\already\\long"),
        ("\\\\server\\share\\releases", "\\\\?\\UNC\\server\\share\\releases"),
    ],
)
def test_windows_tree_removal_uses_the_extended_length_path(monkeypatch, path, expected):
    monkeypatch.setattr(runtime, "WINDOWS", True)
    monkeypatch.setattr(runtime.os.path, "abspath", lambda value: value)
    removed = []
    monkeypatch.setattr(runtime.shutil, "rmtree", lambda target, **_hook: removed.append(target))
    runtime._remove_tree(path)
    assert removed == [expected]

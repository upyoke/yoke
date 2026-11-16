"""The final CLI removal waits for the uninstall process and exposes its outcome."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from yoke_cli.config import machine_uninstall_detached as detached, cli_release_runtime
from yoke_contracts import platform_file_lock, shell_path_state


@pytest.fixture
def handoff_files(tmp_path):
    lock = tmp_path / detached.LOCK_NAME
    lock.touch()
    return lock, tmp_path / "armed", tmp_path / "ready"


def _finish(handoff_files, tmp_path):
    return detached.finish(*handoff_files, tmp_path / "tools", tmp_path / "bin")


def test_finish_waits_for_the_parent_lock_before_removing(
    handoff_files, tmp_path, monkeypatch, capsys
):
    _lock, armed, ready = handoff_files
    armed.write_text("armed")
    events = []
    monkeypatch.setattr(
        platform_file_lock,
        "acquire_exclusive",
        lambda descriptor: events.append("parent exited"),
    )
    monkeypatch.setattr(
        cli_release_runtime,
        "uninstall",
        lambda root, bin_dir: events.append((root, bin_dir)),
    )
    monkeypatch.setattr(
        shell_path_state, "remove_shell_path", lambda: events.append("PATH") or []
    )
    assert _finish(handoff_files, tmp_path) == 0
    assert events == [
        "parent exited",
        (tmp_path / "tools", tmp_path / "bin"),
        "PATH",
    ]
    assert ready.is_file()
    output = capsys.readouterr().out
    assert "CLI: done" in output and "shell PATH: done" in output


def test_unarmed_worker_never_removes_cli(handoff_files, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli_release_runtime,
        "uninstall",
        lambda *args: pytest.fail("must not remove CLI"),
    )
    assert _finish(handoff_files, tmp_path) == 1
    assert "CLI: skipped" in capsys.readouterr().out


def test_cli_removal_failure_keeps_path_and_names_recovery(
    handoff_files, tmp_path, monkeypatch, capsys
):
    handoff_files[1].touch()

    def refuse(root, bin_dir):
        raise OSError("launcher is open")

    monkeypatch.setattr(cli_release_runtime, "uninstall", refuse)
    monkeypatch.setattr(
        shell_path_state,
        "remove_shell_path",
        lambda: pytest.fail("PATH must stay while the CLI does"),
    )
    assert _finish(handoff_files, tmp_path) == 1
    output = capsys.readouterr().out
    assert "uninstall_cli_failed" in output and "retry yoke uninstall" in output


def test_temp_directory_inside_home_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(detached.tempfile, "gettempdir", lambda: str(tmp_path / "t"))
    with pytest.raises(RuntimeError, match="uninstall_temp_inside_home"):
        detached.prepare(tmp_path)
    assert detached.temp_root(tmp_path / "home") == tmp_path.resolve() / "t"


def test_windows_detaches_without_a_posix_session(monkeypatch):
    monkeypatch.setattr(detached.os, "name", "nt")
    monkeypatch.setattr(detached.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(
        detached.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False
    )
    assert detached._detached() == {"creationflags": 0x208}


def test_finisher_runs_isolated_base_python_with_pure_package_roots(
    tmp_path, monkeypatch
):
    started = []

    class Started:
        def __init__(self, argv, **kwargs):
            started.append((argv, kwargs))
            Path(argv[5]).write_text("ready")

        def poll(self):
            return None

    monkeypatch.setattr(detached.shutil, "which", lambda name: "/bin/uv")
    monkeypatch.setattr(
        detached, "_uv_directory", lambda uv, args: tmp_path / "-".join(args)
    )
    monkeypatch.setattr(detached.subprocess, "Popen", Started)
    monkeypatch.setattr(detached.tempfile, "gettempdir", lambda: str(tmp_path))
    handoff = detached.prepare(tmp_path / "home")
    try:
        argv, kwargs = started[0]
        assert argv[:2] == [sys._base_executable, "-I"]
        assert argv[6:8] == [
            str(tmp_path / "dir/yoke-cli-releases"),
            str(tmp_path / "dir---bin"),
        ]
        assert all(
            Path(root, "yoke_contracts").is_dir() or Path(root, "yoke_cli").is_dir()
            for root in argv[8:]
        )
        assert kwargs["start_new_session"] is True
        # The parent holds the lock the finisher waits for.
        probe = os.open(argv[3], os.O_RDWR)
        with pytest.raises(BlockingIOError):
            platform_file_lock.acquire_exclusive_nonblocking(probe)
        os.close(probe)
    finally:
        os.close(handoff.lock_descriptor)


def test_real_detached_handoff_survives_main_exit(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    root = tmp_path / "tools/yoke-cli-releases"
    generation = root / "releases/1.0"
    generation.mkdir(parents=True)
    (generation / "lease").touch()
    (root / "current").write_text("1.0\n")
    (root / "launcher").touch()
    (bin_dir / "yoke").write_text(f'#!/bin/sh\nexec python3 {root / "launcher"} "$@"\n')
    uv.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"print({str(bin_dir)!r} if '--bin' in sys.argv else {str(root.parent)!r})\n"
    )
    uv.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    machine_home = tmp_path / "machine"
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setenv("TMPDIR", str(temp))
    code = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from yoke_cli.config.machine_uninstall_detached import prepare\n"
        "handoff = prepare(Path(sys.argv[1]))\n"
        "handoff.arm()\n"
        "print(json.dumps({'log': str(handoff.log)}), flush=True)\n"
        "time.sleep(0.5)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", code, str(machine_home)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        report = json.loads(parent.stdout.readline())
        log = Path(report["log"])
        assert temp.resolve() in log.parents
        assert root.exists(), "detached worker raced the main process"
        assert parent.wait(timeout=10) == 0
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if "shell PATH:" in log.read_text():
                break
            time.sleep(0.05)
        assert not root.exists(), log.read_text()
        assert not (bin_dir / "yoke").exists()
        assert "CLI: done" in log.read_text()
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)

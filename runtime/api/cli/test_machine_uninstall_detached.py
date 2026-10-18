"""The final uv removal waits for process exit and exposes its outcome."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from yoke_cli.config import machine_uninstall_detached as detached, cli_release_runtime


def test_finish_does_not_run_uv_until_parent_is_gone(tmp_path, monkeypatch, capsys):
    armed, ready = tmp_path / "armed", tmp_path / "ready"
    armed.write_text("armed")
    checks = iter([True, True, False])
    events = []
    monkeypatch.setattr(detached, "_parent_running", lambda *args: next(checks))
    monkeypatch.setattr(detached.time, "sleep", lambda delay: events.append("wait"))
    monkeypatch.setattr(
        detached.subprocess,
        "run",
        lambda args, **kwargs: (
            events.append(args)
            or subprocess.CompletedProcess(
                args, 0, str(tmp_path / ("bin" if "--bin" in args else "tools")), ""
            )
        ),
    )
    monkeypatch.setattr(
        cli_release_runtime,
        "uninstall",
        lambda root, bin_dir: events.append((root, bin_dir)),
    )
    assert detached.finish(123, "start", "/bin/uv", armed, ready) == 0
    assert events == [
        "wait",
        "wait",
        ["/bin/uv", "tool", "dir"],
        ["/bin/uv", "tool", "dir", "--bin"],
        (tmp_path / "tools/yoke-cli-releases", tmp_path / "bin"),
    ]
    assert ready.is_file()
    assert "CLI: done" in capsys.readouterr().out


def test_unarmed_worker_never_removes_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(detached, "_parent_running", lambda *args: False)
    monkeypatch.setattr(
        detached.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("must not remove CLI"),
    )
    assert (
        detached.finish(123, "start", "/bin/uv", tmp_path / "armed", tmp_path / "ready")
        == 1
    )
    assert "CLI: skipped" in capsys.readouterr().out


def test_uv_failure_has_named_recovery(tmp_path, monkeypatch, capsys):
    armed = tmp_path / "armed"
    armed.touch()
    monkeypatch.setattr(detached, "_parent_running", lambda *args: False)
    monkeypatch.setattr(
        detached.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 7, "", "uv failed"),
    )
    assert detached.finish(123, "start", "/bin/uv", armed, tmp_path / "ready") == 1
    output = capsys.readouterr().out
    assert "uninstall_cli_failed" in output and "retry yoke uninstall" in output


def test_missing_process_snapshot_does_not_prove_parent_exit(monkeypatch):
    monkeypatch.setattr(detached, "process_start_time", lambda pid: None)
    monkeypatch.setattr(detached.os, "kill", lambda pid, sig: None)
    assert detached._parent_running(123, "start")


def test_real_detached_handoff_survives_main_exit(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    root = tmp_path / "tools/yoke-cli-releases"
    generation = root / "releases/1.0"
    generation.mkdir(parents=True)
    (generation / "lease").touch()
    (root / "current").symlink_to(generation)
    (root / "launcher").touch()
    (bin_dir / "yoke").symlink_to(root / "launcher")
    uv.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"print({str(bin_dir)!r} if '--bin' in sys.argv else {str(root.parent)!r})\n"
    )
    uv.chmod(0o700)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    # A session's temporary root may be Yoke-owned; the final handoff must not be.
    doomed_temp = tmp_path / "machine-temp"
    doomed_temp.mkdir()
    monkeypatch.setenv("TMPDIR", str(doomed_temp))
    code = (
        "import json, time\n"
        "from yoke_cli.config.machine_uninstall_detached import prepare\n"
        "handoff = prepare()\n"
        "handoff.arm()\n"
        "print(json.dumps({'log': str(handoff.log)}), flush=True)\n"
        "time.sleep(0.5)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        report = json.loads(parent.stdout.readline())
        assert doomed_temp not in Path(report["log"]).parents
        assert root.exists(), "detached worker raced the main process"
        assert parent.wait(timeout=10) == 0
        deadline = time.monotonic() + 10
        log = Path(report["log"])
        while time.monotonic() < deadline:
            if "CLI: done" in log.read_text():
                break
            time.sleep(0.05)
        assert not root.exists()
        assert "CLI: done" in log.read_text()
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)

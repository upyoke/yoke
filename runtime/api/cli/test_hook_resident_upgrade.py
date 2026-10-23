"""Self-exec crosses immutable generations without releasing resident ownership."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest

from runtime.api.cli.test_cli_release_runtime import candidate
from runtime.api.cli.test_yoke_hook_resident import _request, _round_trip
from yoke_cli.config import cli_release_runtime as runtime
from yoke_contracts.hook_evaluator_protocol import receive_frame, send_frame


def _resident_candidate(root, version, revision):
    generation = candidate(root, version)
    site = next((generation / "tools/yoke-cli/lib").glob("python*/site-packages"))
    sources = Path(__file__).resolve().parents[3] / "packages"
    main = (site / "yoke_cli/main.py").read_text()
    binding = (site / "yoke_cli/config/install_binding.py").read_text()
    for package in ("cli", "harness", "contracts"):
        name = f"yoke_{package}"
        shutil.copytree(
            sources / f"yoke-{package}/src" / name,
            site / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    (site / "dependencies.pth").write_text(str(Path(httpx.__file__).parents[1]) + "\n")
    (site / "yoke_cli/main.py").write_text(main)
    (site / "yoke_cli/config/install_binding.py").write_text(binding)
    metadata = site / "yoke_contracts-1.0.dist-info"
    metadata.mkdir()
    (metadata / "RECORD").write_text("yoke_contracts/execution_provenance.py,,\n")
    (metadata / "METADATA").write_text("Name: yoke-contracts\nVersion: 1.0\n")
    (metadata / "scm_version.json").write_text(json.dumps({"node": f"g{revision}"}))
    (site / "yoke_cli/commands/adapters/hook_inprocess.py").write_text(
        "import json, os, sys\nRESIDENT_PID = os.getpid()\n"
        "def evaluate_inprocess(*args, **kwargs):\n"
        '    print(json.dumps({"python": sys.executable, "pid": RESIDENT_PID}))\n'
        "    return 0\n"
    )
    return generation


def _health(address):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(1)
        peer.connect(str(address))
        send_frame(peer, {"kind": "health"})
        return receive_frame(peer)


def _wait_revision(address, revision, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        assert process.poll() is None, process.communicate()[1]
        try:
            if _health(address).get("loaded_revision") == revision:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.025)
    pytest.fail(f"resident did not serve revision {revision}")


def test_main_self_exec_uses_current_and_retains_lock_and_cleanup_protection(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("COLUMNS", "40")
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old_revision, new_revision = "a" * 40, "b" * 40
    old = _resident_candidate(root, "1.0", old_revision)
    runtime.activate(root, old, bin_dir, "1.0")
    # Keep Unix socket paths within the platform limit, independent of pytest's root.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="hook-upgrade-") as short:
        address = Path(short) / "resident.sock"
        with (tmp_path / "start.lock").open("a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            lock_fd = held.fileno()
            environment = dict(os.environ)
            for name in ("PYTHONPATH", "PYTHONHOME", "YOKE_BUILD_SHA"):
                environment.pop(name, None)
            process = subprocess.Popen(
                [
                    str(old / "tools/yoke-cli/bin/python3"),
                    "-m",
                    "yoke_harness.hook_resident",
                    "--socket",
                    str(address),
                    "--lock-fd",
                    str(lock_fd),
                ],
                pass_fds=(lock_fd,),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        try:
            _wait_revision(address, old_revision, process)
            assert str(old) in runtime._process_commands()
            new = _resident_candidate(root, "2.0", new_revision)
            runtime.activate(root, new, bin_dir, "2.0")
            assert old.exists(), "cleanup must protect the running old interpreter"
            response = _round_trip(
                str(address),
                _request(
                    "SessionStart",
                    cwd=str(tmp_path),
                    revision=new_revision,
                ),
            )
            assert response == {
                "status": "restart",
                "loaded_revision": old_revision,
                "requested_revision": new_revision,
            }
            _wait_revision(address, new_revision, process)
            assert str(new) in runtime._process_commands()
            for _ in range(3):
                response = _round_trip(
                    str(address),
                    _request(
                        "PreToolUse",
                        cwd=str(tmp_path),
                        revision=new_revision,
                    ),
                )
                assert response["status"] == "ok", response
                assert response["exit_code"] == 0, response
                assert json.loads(response["stdout"]) == {
                    "python": str(new / "tools/yoke-cli/bin/python3"),
                    "pid": process.pid,
                }
            with (tmp_path / "start.lock").open("a+") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Exec closes the publication lock; process identity protects the
            # running generation even when current points elsewhere.
            with runtime.locked(root / "publication.lock", nonblocking=True):
                runtime._point(root / "current", old)
                runtime.collect(root)
                assert new.exists()
                runtime._point(root / "current", new)
                runtime.collect(root)
                assert not old.exists()
        finally:
            process.terminate()
            _, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        assert not address.exists()
        with (tmp_path / "start.lock").open("a+") as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_source_development_restart_keeps_its_interpreter(monkeypatch, tmp_path):
    python = tmp_path / "source/.venv/bin/python3"
    monkeypatch.setattr(sys, "executable", str(python))
    calls = []
    monkeypatch.setattr(os, "execv", lambda *args: calls.append(args))
    assert runtime.exec_current_python(["-m", "yoke_harness.hook_resident"]) == 0
    assert calls == [(str(python), [str(python), "-m", "yoke_harness.hook_resident"])]


def test_broken_current_names_restart_failure_and_recovery(
    monkeypatch, tmp_path, capsys
):
    python = tmp_path / "runtime/releases/old/tools/yoke-cli/bin/python3"
    monkeypatch.setattr(sys, "executable", str(python))
    (tmp_path / "runtime").mkdir()
    assert runtime.exec_current_python(["-m", "yoke_harness.hook_resident"]) == 2
    error = capsys.readouterr().err
    assert "hook_resident_restart_failed" in error
    assert "yoke update" in error
    assert "yoke hook resident restart" in error

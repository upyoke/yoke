"""Relay packages and launchers work with copies and Windows venv layouts."""

from pathlib import Path
import shutil

import pytest

from runtime.api.tools.session_relay_release_test_support import (
    RELEASE, NEXT_RELEASE, fake_venv, relay_instance, runner_for,
)
from yoke_core.tools import session_relay_links as links
from yoke_core.tools import session_relay_release as release
from yoke_core.tools import session_relay_runtime_install as runtime
from yoke_core.tools.session_relay_release_install import pin_relay_release
from yoke_core.domain import relay_release_path as paths
from yoke_harness import session_relay_process_restart as restart


def test_copy_fallback_keeps_physical_release_selection_and_rollback(tmp_path, monkeypatch):
    def copy(target, path):
        shutil.copytree(target, path)
        return "copy"

    monkeypatch.setattr(links, "link", copy)
    instance = relay_instance(tmp_path)
    roots = []
    for version in (RELEASE, NEXT_RELEASE):
        status = pin_relay_release(instance=instance, served_build=version,
                                  create_venv=fake_venv, runner=runner_for(version, []))
        assert status.package_ready
        receipt = release.relay_release_receipt(instance.state_dir)
        roots.append(Path(receipt["physical_root"]))
        assert roots[-1].parent == instance.state_dir / "releases"
    assert roots[0].is_dir() and roots[1].is_dir()
    assert receipt["previous_release"] == str(roots[0])
    assert release.relay_launch_targets_runtime(instance.state_dir)
    assert not (instance.state_dir / "venv").is_symlink()


def test_failed_link_activation_keeps_previous_selection(tmp_path, monkeypatch):
    target, active = tmp_path / "new", tmp_path / "active"
    target.mkdir()
    active.mkdir()
    (active / "keep").write_text("previous")
    monkeypatch.setattr(links, "link", lambda *a: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(OSError, match="denied"):
        links.activate_link(target, active)
    assert (active / "keep").read_text(encoding="utf-8") == "previous"


def test_windows_runtime_launches_python_explicitly_and_bundles_shared_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    root = tmp_path / "runtime"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").touch()
    runtime._install_runtime_entrypoint(root, state_dir=tmp_path)
    command = (scripts / "yoke.cmd").read_text(encoding="utf-8")
    assert "python.exe" in command and "-I" in command and "yoke.py" in command
    assert (root / "relay_file_lock.py").read_text(encoding="utf-8") == Path(runtime.platform_file_lock.__file__).read_text(encoding="utf-8")
    assert "import fcntl" not in (scripts / "yoke.py").read_text(encoding="utf-8")
    assert release.relay_runtime_python(tmp_path) == scripts / "python.exe"
    calls = []
    results = iter([restart.WINDOWS_RELAY_RESTART_CODE, 0])
    monkeypatch.delenv(restart.WINDOWS_RELAY_RUNNER_ENV, raising=False)
    monkeypatch.setattr(restart.subprocess, "call", lambda argv, **kw: calls.append((argv, kw)) or next(results))
    with pytest.raises(SystemExit) as exited:
        restart.exec_relay_release(["relay", "serve"], executable=scripts / "yoke.cmd")
    assert exited.value.code == 0 and len(calls) == 2
    assert calls[0][0] == [str(scripts / "python.exe"), "-I", str(scripts / "yoke.py"), "relay", "serve"]
    assert calls[0][1]["env"][restart.WINDOWS_RELAY_RUNNER_ENV] == "1"


def test_windows_managed_relay_requests_recycle_without_losing_its_supervisor(monkeypatch):
    monkeypatch.setattr(restart.sys, "platform", "win32")
    monkeypatch.setenv(restart.WINDOWS_RELAY_RUNNER_ENV, "1")
    monkeypatch.setattr(restart.subprocess, "call", lambda *a, **k: pytest.fail("runner owns restart"))
    with pytest.raises(SystemExit) as exited:
        restart.exec_relay_release(["relay", "serve"])
    assert exited.value.code == restart.WINDOWS_RELAY_RESTART_CODE


def test_windows_release_installs_scripts_layout_without_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(links, "link", lambda target, path: shutil.copytree(target, path))
    instance = relay_instance(tmp_path)

    def create_runtime(root):
        python = root / "Scripts" / "python.exe"
        python.parent.mkdir(parents=True)
        python.touch()
        python.chmod(0o700)

    status = pin_relay_release(instance=instance, served_build=RELEASE,
                              create_runtime=create_runtime, create_venv=fake_venv,
                              runner=runner_for(RELEASE, []))
    assert status.current
    assert status.runtime_python.name == "python.exe"
    assert status.launch_executable.name == "yoke.cmd"
    assert release.relay_package_executable(instance.state_dir).name == "yoke.exe"
    assert (instance.state_dir / "runtime" / "Scripts" / "yoke.py").is_file()

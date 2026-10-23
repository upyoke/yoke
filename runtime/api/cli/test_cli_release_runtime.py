"""Real subprocess proof for CLI publication, retained imports and retirement."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from yoke_cli.config import cli_release_runtime as runtime


def candidate(root: Path, version: str) -> Path:
    generation = root / "releases" / version
    binary = generation / "tools" / "yoke-cli" / "bin" / "yoke"
    environment = binary.parent.parent
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(environment)],
        check=True,
        capture_output=True,
    )
    site = next((environment / "lib").glob("python*/site-packages"))
    (site / "release_marker.py").write_text(f"VERSION = {version!r}\n")
    package = site / "yoke_cli"
    (package / "config").mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "config/__init__.py").touch()
    (package / "config/install_binding.py").write_text(
        "def detect(): return {'kind': 'packaged_wheel', 'version': '1.0'}\n"
    )
    (package / "main.py").write_text(
        "import json, sys\n"
        "def main(argv):\n"
        "    if argv == ['long']:\n"
        "        print('ready', flush=True)\n"
        "        sys.stdin.readline()\n"
        "        import release_marker\n"
        "        print(release_marker.VERSION, flush=True)\n"
        "    elif argv == ['hold']:\n"
        "        import os\n"
        "        print(os.getpid(), flush=True)\n"
        "        sys.stdin.readline()\n"
        "    elif argv == ['--version']:\n"
        "        import release_marker\n"
        "        print(release_marker.VERSION)\n"
        "    elif argv[:1] == ['github']:\n"
        "        print(json.dumps({'configured': False}))\n"
    )
    binary.write_text(
        f"#!{environment}/bin/python3\nfrom yoke_cli.main import main\nimport sys\nsys.exit(main(sys.argv[1:]))\n"
    )
    binary.chmod(0o755)
    (generation / "lease").touch()
    (generation / "pending").touch()
    return generation


def test_update_retains_running_command_imports_and_next_command_uses_new_release(
    tmp_path,
):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    running = subprocess.Popen(
        [str(bin_dir / "yoke"), "long"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert running.stdout.readline().strip() == "ready"
        new = candidate(root, "2.0")
        runtime.activate(root, new, bin_dir, "2.0")
        assert old.is_dir()
        next_command = subprocess.run(
            [str(bin_dir / "yoke"), "--version"], capture_output=True, text=True
        )
        assert next_command.returncode == 0, next_command.stderr
        assert next_command.stdout.strip() == "2.0"
        stdout, stderr = running.communicate("finish\n", timeout=10)
        assert running.returncode == 0, stderr
        assert stdout.strip() == "1.0"
        assert not old.exists()
        assert new.is_dir()
    finally:
        if running.poll() is None:
            running.kill()
            running.communicate()


@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGKILL])
def test_stopping_the_launcher_ends_its_command(tmp_path, stop):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    runtime.activate(root, candidate(root, "1.0"), bin_dir, "1.0")
    launcher = subprocess.Popen(
        [str(bin_dir / "yoke"), "hold"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        command = int(launcher.stdout.readline())
        launcher.send_signal(stop)
        launcher.wait(timeout=10)
        deadline = time.monotonic() + 10
        while _running(command) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _running(command), "the command outlived its launcher"
    finally:
        launcher.kill()
        launcher.communicate()


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_broken_candidate_preserves_public_command(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    bad = candidate(root, "2.0")
    with pytest.raises(RuntimeError, match="cli_candidate_version_mismatch"):
        runtime.activate(root, bad, bin_dir, "3.0")
    assert (root / "current").resolve() == old
    assert (
        subprocess.check_output([str(bin_dir / "yoke"), "--version"], text=True).strip()
        == "1.0"
    )


def test_cleanup_preserves_install_in_progress_and_uninstall_requires_released_leases(
    tmp_path,
):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    active = candidate(root, "1.0")
    runtime.activate(root, active, bin_dir, "1.0")
    pending = candidate(root, "2.0")
    with runtime.locked(pending / "lease", shared=True):
        with runtime.locked(root / "publication.lock"):
            runtime.collect(root)
        assert pending.is_dir()
        with pytest.raises(BlockingIOError):
            runtime.uninstall(root, bin_dir)
    runtime.uninstall(root, bin_dir)
    assert not root.exists()
    assert not (bin_dir / "yoke").exists()


def test_real_installer_runner_isolates_uv_and_activates_candidate(
    tmp_path, monkeypatch
):
    installer_path = (
        Path(__file__).resolve().parents[3] / "packaging/public-installer/install.py"
    )
    spec = importlib.util.spec_from_file_location(
        "isolated_public_installer", installer_path
    )
    installer = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, installer)
    spec.loader.exec_module(installer)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs.get("env", {})))
        output = ""
        if command == ["uv", "tool", "dir"]:
            output = str(tmp_path / "tools")
        elif command == ["uv", "tool", "dir", "--bin"]:
            output = str(tmp_path / "bin")
        elif command[3:4] == [installer.HELPER_SOURCE_CHECK]:
            output = '{"checked": 19, "unsafe_permissions": [], "refusal": null}'
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(installer.subprocess, "run", run)
    command = ["uv", "tool", "install", "yoke-cli==1.0", "--reinstall"]
    result = installer.run_command_capture(command)
    assert result.returncode == 0
    install, environment = next(call for call in calls if call[0] == command)
    assert install == command
    generation = Path(environment["UV_TOOL_DIR"]).parent
    assert generation.parent == tmp_path / "tools/yoke-cli-releases/releases"
    assert environment["UV_TOOL_BIN_DIR"] == str(generation / "bin")
    activation, _ = calls[-1]
    assert activation[1:3] == ["-I", str(generation / "runtime.py")]
    assert (generation / "runtime.py").read_text() == Path(runtime.__file__).read_text()
    assert activation[-3:] == [str(generation), str(tmp_path / "bin"), "1.0"]


def test_downloadable_installer_matches_its_authored_sources():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "packaging/public-installer/build.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    from yoke_core.domain.file_line_check_helpers import (
        Classification,
        do_classify_path,
    )

    assert (
        do_classify_path(
            "packaging/public-installer/install.py",
            repo_root=root,
            temporary_exceptions=("packaging/public-installer/*",),
            archive_exceptions=(),
        )
        == Classification.GENERATED
    )
    for source in (root / "packaging/public-installer/source").glob("*.inc"):
        assert len(source.read_text().splitlines()) <= 350, source


def test_publication_failure_preserves_prior_release_and_pending_helper_files(
    tmp_path, monkeypatch
):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    new = candidate(root, "2.0")
    point = runtime._point

    def refuse_launcher(path, target):
        if path == bin_dir / "yoke":
            raise PermissionError("launcher is read-only")
        point(path, target)

    monkeypatch.setattr(runtime, "_point", refuse_launcher)
    with pytest.raises(PermissionError):
        runtime.activate(root, new, bin_dir, "2.0")
    assert (root / "current").resolve() == old
    assert (new / "pending").exists()
    assert (
        subprocess.check_output([str(bin_dir / "yoke"), "--version"], text=True).strip()
        == "1.0"
    )
    assert new.exists(), (
        "a failed publication may already have repaired helper references"
    )
    monkeypatch.setattr(runtime, "_point", point)
    runtime.activate(root, new, bin_dir, "2.0")
    assert not old.exists()
    assert not (new / "pending").exists()


def test_standalone_bootstrap_activates_wheel_without_runtime_module(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    generation = candidate(root, "1.0")
    script = generation / "runtime.py"
    script.write_text(Path(runtime.__file__).read_text())
    python = generation / "tools/yoke-cli/bin/python3"
    result = subprocess.run(
        [
            str(python),
            "-I",
            str(script),
            str(root),
            str(generation),
            str(bin_dir),
            "1.0",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (
        subprocess.check_output([str(bin_dir / "yoke"), "--version"], text=True).strip()
        == "1.0"
    )


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


def test_resident_exec_holds_publication_lock_and_keeps_virtualenv_path(
    tmp_path, monkeypatch
):
    import fcntl

    root = tmp_path / "runtime"
    old = root / "releases/old/tools/yoke-cli/bin/python3"
    new = root / "releases/new/tools/yoke-cli/bin/python3"
    old.parent.mkdir(parents=True)
    new.parent.mkdir(parents=True)
    new.symlink_to(sys.executable)
    runtime._point(root / "current", new.parents[3])
    monkeypatch.setattr(sys, "executable", str(old))
    calls = []

    def replace(python, arguments):
        with (root / "publication.lock").open("a+") as contender:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        calls.append((python, arguments))

    monkeypatch.setattr(os, "execv", replace)
    assert runtime.exec_current_python(["-m", "yoke_harness.hook_resident"]) == 0
    assert calls == [(str(new), [str(new), "-m", "yoke_harness.hook_resident"])]

"""Real subprocess proof for CLI publication, retained releases and cleanup.

These run on macOS, Linux and Windows CI with the same layout.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.api.cli.cli_release_runtime_test_support import (
    candidate,
    running,
    version,
    yoke,
)
from yoke_cli.config import cli_release_runtime as runtime


def test_two_commands_across_an_update_and_cleanup_after_the_old_one_exits(
    tmp_path,
):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    assert not (root / "current").is_symlink()
    assert (root / "current").read_text() == "1.0\n"
    first = subprocess.Popen(
        [yoke(bin_dir), "long"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert first.stdout.readline().strip() == "ready"
        new = candidate(root, "2.0")
        runtime.activate(root, new, bin_dir, "2.0")
        assert old.is_dir(), "an update deleted a running release"
        assert version(bin_dir) == "2.0"
        stdout, stderr = first.communicate("finish\n", timeout=20)
        assert first.returncode == 0, stderr
        # The running command still imported from its own release.
        assert stdout.strip() == "1.0"
        assert not old.exists(), "the last command on a replaced release retires it"
        assert not any((root / "retired").iterdir())
        assert new.is_dir()
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()


def test_failed_candidate_preserves_public_command_and_is_cleaned_later(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    bad = candidate(root, "2.0")
    with pytest.raises(RuntimeError, match="cli_candidate_version_mismatch"):
        runtime.activate(root, bad, bin_dir, "3.0")
    assert runtime._generation(root) == old
    assert version(bin_dir) == "1.0"
    assert bad.is_dir()
    runtime.activate(root, candidate(root, "4.0"), bin_dir, "4.0")
    assert not bad.exists() and not old.exists()
    assert version(bin_dir) == "4.0"


def test_cleanup_keeps_installs_in_progress_and_uninstall_waits_for_them(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    runtime.activate(root, candidate(root, "1.0"), bin_dir, "1.0")
    pending = candidate(root, "2.0")
    with running(pending):
        with runtime.locked(root / "publication.lock"):
            runtime.collect(root, pending_safe=True)
        assert pending.is_dir()
        with pytest.raises(BlockingIOError):
            runtime.uninstall(root, bin_dir)
        assert version(bin_dir) == "1.0", "a refused uninstall broke the CLI"
    with runtime.locked(root / "publication.lock"):
        runtime.collect(root)
    assert pending.is_dir(), "plain cleanup never removes an install in progress"
    runtime.uninstall(root, bin_dir)
    assert not root.exists()
    assert not Path(yoke(bin_dir)).exists()
    assert not (bin_dir / "yoke").exists()


def test_python_shim_runs_the_current_release_python(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    runtime.activate(root, candidate(root, "1.0"), bin_dir, "1.0")
    runtime.activate(root, candidate(root, "2.0"), bin_dir, "2.0")
    script = "import release_marker, sys; print(release_marker.VERSION, sys.argv[1:])"
    command = [str(root / "python"), "-c", script, "a b"]
    if runtime.WINDOWS:
        command = [sys.executable, str(root / "launcher"), "--python", *command[1:]]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "2.0 ['a b']"


def test_publication_failure_preserves_prior_release(tmp_path, monkeypatch):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    old = candidate(root, "1.0")
    runtime.activate(root, old, bin_dir, "1.0")
    new = candidate(root, "2.0")
    replace = runtime._replace

    def refuse_launcher(path, content, **options):
        if path.parent == bin_dir:
            raise PermissionError("launcher is read-only")
        replace(path, content, **options)

    monkeypatch.setattr(runtime, "_replace", refuse_launcher)
    with pytest.raises(PermissionError):
        runtime.activate(root, new, bin_dir, "2.0")
    assert runtime._generation(root) == old
    assert (new / "pending").exists()
    assert version(bin_dir) == "1.0"
    monkeypatch.setattr(runtime, "_replace", replace)
    runtime.activate(root, new, bin_dir, "2.0")
    assert not old.exists()
    assert not (new / "pending").exists()


def test_standalone_bootstrap_activates_wheel_without_runtime_module(tmp_path):
    root, bin_dir = tmp_path / "runtime", tmp_path / "bin"
    generation = candidate(root, "1.0")
    script = generation / "runtime.py"
    script.write_text(Path(runtime.__file__).read_text())
    python = runtime.release_python(generation)
    result = subprocess.run(
        [str(python), "-I", str(script), str(root), str(generation), str(bin_dir)]
        + ["1.0"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert version(bin_dir) == "1.0"


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

"""Install-flow tests for ``install_yoke_launcher``."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.tools import install_yoke_launcher as isl


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "yoke-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\n'
        'name = "yoke"\n'
        'version = "0.1.0"\n'
        'dependencies = [\n'
        '    "fastapi==0.128.8",\n'
        ']\n'
    )
    return repo


def _fake_source(repo: Path) -> Path:
    src = repo / "_fake_launcher.py"
    src.write_text(
        "#!/usr/bin/env python3\n"
        "from yoke_cli.main import main\n"
    )
    return src


@pytest.fixture
def install_env(monkeypatch):
    monkeypatch.setattr(isl, "verify_python_version", lambda **kw: None)
    monkeypatch.setattr(isl, "_is_externally_managed", lambda: False)
    monkeypatch.setattr(isl, "cleanup_stale_editable_yoke_metadata", lambda *a, **kw: 0)
    monkeypatch.setattr(isl.subprocess, "check_call", lambda *a, **kw: 0)
    return monkeypatch


def test_install_skip_claude_config_propagates(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    called = []

    def spy(*, config_path=None, stream=None):
        called.append(True)
        return False

    install_env.setattr(isl, "configure_claude_app_bypass_permissions", spy)
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(tmp_path / "bin"),
        skip_claude_config=True,
        stream=io.StringIO(),
    )
    assert called == []


def test_install_default_invokes_claude_config(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    called = []

    def spy(*, config_path=None, stream=None):
        called.append(True)
        return False

    install_env.setattr(isl, "configure_claude_app_bypass_permissions", spy)
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(tmp_path / "bin"),
        stream=io.StringIO(),
    )
    assert called == [True]


def test_install_happy_path_writes_launcher(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    target_dir = tmp_path / "bin"
    choice = isl.install(
        cwd=repo, home=repo, target_dir=str(target_dir), stream=io.StringIO(),
    )
    assert choice.label == "override"
    written = target_dir / isl.LAUNCHER_FILENAME
    assert written.is_file()
    assert (written.stat().st_mode & 0o777) == 0o755


def test_install_is_idempotent(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    target_dir = tmp_path / "bin"
    isl.install(cwd=repo, home=repo, target_dir=str(target_dir), stream=io.StringIO())
    target_path = target_dir / isl.LAUNCHER_FILENAME
    first_content = target_path.read_text()
    isl.install(cwd=repo, home=repo, target_dir=str(target_dir), stream=io.StringIO())
    assert target_path.read_text() == first_content
    assert (target_path.stat().st_mode & 0o777) == 0o755


def test_install_refuses_foreign_binary_without_force(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    (target_dir / isl.LAUNCHER_FILENAME).write_text("#!/bin/bash\necho foreign\n")
    with pytest.raises(isl.InstallError, match="not a python interpreter"):
        isl.install(cwd=repo, home=repo, target_dir=str(target_dir), stream=io.StringIO())


def test_install_force_overwrites_foreign_binary(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    foreign = target_dir / isl.LAUNCHER_FILENAME
    foreign.write_text("#!/bin/bash\necho foreign\n")
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(target_dir),
        force=True,
        stream=io.StringIO(),
    )
    new_text = foreign.read_text()
    assert new_text.startswith(f"#!{sys.executable}\n")
    assert isl.LAUNCHER_FINGERPRINT_IMPORT in new_text


def test_install_skip_pip_and_skip_verify_avoid_subprocess(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(isl, "verify_python_version", lambda **kw: None)
    repo = _fake_repo(tmp_path)
    monkeypatch.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    calls = []
    monkeypatch.setattr(
        isl.subprocess,
        "check_call",
        lambda *a, **kw: calls.append(tuple(a[0]) if a else ()),
    )
    target_dir = tmp_path / "bin"
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(target_dir),
        skip_pip=True,
        skip_verify=True,
        stream=io.StringIO(),
    )
    assert calls == []


def test_install_system_flag_picks_usr_local_bin(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "write_launcher", lambda *a, **kw: None)
    install_env.setattr(isl, "verify_path_includes", lambda *a, **kw: True)
    install_env.setattr(isl, "refuse_foreign_binary", lambda *a, **kw: None)
    choice = isl.install(
        cwd=repo,
        home=repo,
        force_system=True,
        skip_verify=True,
        stream=io.StringIO(),
    )
    assert choice.label == "homebrew_intel_or_linux"
    assert str(choice.path) == "/usr/local/bin"


def test_main_reports_install_errors_via_exit_code_2(monkeypatch):
    monkeypatch.setattr(isl, "install", mock.Mock(side_effect=isl.InstallError("nope")))
    assert isl.main(["--user"]) == 2


def test_main_reports_subprocess_errors(monkeypatch):
    monkeypatch.setattr(
        isl,
        "install",
        mock.Mock(side_effect=subprocess.CalledProcessError(7, "pip")),
    )
    assert isl.main([]) == 7


def test_main_happy_path_returns_zero(monkeypatch):
    monkeypatch.setattr(isl, "install", mock.Mock(return_value=None))
    assert isl.main(["--user", "--skip-pip", "--skip-verify"]) == 0


def test_install_skip_macos_path_fix_blocks_function(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    called = []

    def spy(*, paths_file=None, brew_bin=None, stream=None):
        called.append(True)
        return False

    install_env.setattr(isl, "configure_macos_path_for_homebrew", spy)
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(tmp_path / "bin"),
        skip_macos_path_fix=True,
        stream=io.StringIO(),
    )
    assert called == []


def test_install_default_invokes_macos_path_fix(tmp_path: Path, install_env):
    repo = _fake_repo(tmp_path)
    install_env.setattr(isl, "LAUNCHER_SOURCE", _fake_source(repo))
    called = []

    def spy(*, paths_file=None, brew_bin=None, stream=None):
        called.append(True)
        return False

    install_env.setattr(isl, "configure_macos_path_for_homebrew", spy)
    isl.install(
        cwd=repo,
        home=repo,
        target_dir=str(tmp_path / "bin"),
        stream=io.StringIO(),
    )
    assert called == [True]

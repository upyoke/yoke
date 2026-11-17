"""A Windows editable install replaces the environment's running ``yoke.exe``."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_cli.config import source_checkout_activation as activation

pytestmark = pytest.mark.windows


def _checkout(root: Path) -> Path:
    for name in ("yoke-contracts", "yoke-core", "yoke-cli", "yoke-harness"):
        (root / "packages" / name).mkdir(parents=True)
        (root / "packages" / name / "pyproject.toml").write_text("", encoding="utf-8")
    return root


def _scripts(tmp_path: Path, monkeypatch) -> Path:
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "yoke.exe").write_text("running", encoding="utf-8")
    (scripts / "yoke.exe.0ld0ld00.replaced").write_text("earlier", encoding="utf-8")
    monkeypatch.setattr(activation, "_WINDOWS", True)
    monkeypatch.setattr(activation.sys, "executable", str(scripts / "python.exe"))
    monkeypatch.setattr(activation, "_find_uv", lambda: "uv")
    monkeypatch.setattr(activation.editable_install, "loader_source", lambda: "")
    return scripts


def test_install_writes_a_new_launcher_beside_the_running_one(tmp_path, monkeypatch):
    scripts = _scripts(tmp_path, monkeypatch)

    def install(command, **kwargs):
        assert not (scripts / "yoke.exe").exists()  # the running copy is out of the way
        (scripts / "yoke.exe").write_text("installed", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(activation.terminal_detached_process, "run", install)
    monkeypatch.setattr(activation.editable_install, "swap_to_config_driven", lambda *a, **k: {})
    monkeypatch.setattr(activation.editable_install, "site_packages_dir", lambda: tmp_path)
    assert activation._run_editable_install(_checkout(tmp_path / "yoke"))["ok"] is True
    assert (scripts / "yoke.exe").read_text(encoding="utf-8") == "installed"
    aside = [path.read_text(encoding="utf-8") for path in scripts.glob("yoke.exe.*.replaced")]
    assert aside == ["running"]  # the earlier, no longer running copy is gone


def test_failed_install_restores_the_running_launcher(tmp_path, monkeypatch):
    scripts = _scripts(tmp_path, monkeypatch)
    monkeypatch.setattr(
        activation.terminal_detached_process,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "resolver failed"),
    )
    with pytest.raises(RuntimeError, match="editable install failed: resolver failed"):
        activation._run_editable_install(_checkout(tmp_path / "yoke"))
    assert (scripts / "yoke.exe").read_text(encoding="utf-8") == "running"
    assert not list(scripts.glob("yoke.exe.*.replaced"))

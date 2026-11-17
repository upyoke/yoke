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


def test_launcher_held_open_refuses_by_name_with_its_holders(tmp_path, monkeypatch):
    scripts = _scripts(tmp_path, monkeypatch)

    def held(self, target):
        raise PermissionError(32, "being used by another process")

    monkeypatch.setattr(activation.Path, "replace", held)
    monkeypatch.setattr(activation.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(activation, "_open_file_holders", lambda path: ["pid 42 `python.exe -m yoke_harness.hook_resident`"])
    with pytest.raises(RuntimeError) as refused:
        activation._set_running_launcher_aside(scripts)
    assert str(refused.value).startswith(
        f"editable_install_launcher_in_use: {scripts / 'yoke.exe'} is held open by pid 42 `python.exe -m yoke_harness.hook_resident`"
    )
    assert "yoke dev setup --editable-install" in str(refused.value)


def test_a_zipapp_launcher_is_not_held_open_after_metadata_scans(tmp_path):
    """The launcher archive leaves sys.path, so importlib.metadata never caches it."""
    import sys
    import zipfile

    launcher = tmp_path / "yoke.exe"
    with zipfile.ZipFile(launcher, "w") as archive:
        archive.writestr(
            "__main__.py",
            "import os, sys, importlib.metadata, psutil\n"
            "import yoke_cli\n"
            "list(importlib.metadata.distributions())\n"
            "held = [f.path for f in psutil.Process().open_files()]\n"
            "print(sys.argv[0] in sys.path, any(os.path.samefile(p, sys.argv[0]) for p in held))\n",
        )
    result = subprocess.run(
        [sys.executable, str(launcher)], capture_output=True, text=True, timeout=120
    )
    assert result.stdout.split() == ["False", "False"], result.stderr


def test_only_the_running_archive_leaves_sys_path(monkeypatch, tmp_path):
    import yoke_cli

    stdlib = tmp_path / "python313.zip"
    stdlib.write_bytes(b"")
    monkeypatch.setattr(yoke_cli._sys, "argv", [str(tmp_path / "script.py")])
    monkeypatch.setattr(yoke_cli._sys, "path", [str(stdlib), "site-packages"])
    yoke_cli._release_launcher_archive()
    assert yoke_cli._sys.path == [str(stdlib), "site-packages"]

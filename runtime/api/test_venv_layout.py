"""Native venv paths and bootstrap launchers agree without package discovery."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts import venv_layout as layout
from yoke_cli.config import cli_release_runtime


@pytest.mark.parametrize("windows", [False, True])
def test_layout_matches_standalone_release_launcher(tmp_path, monkeypatch, windows):
    monkeypatch.setattr(layout, "os", SimpleNamespace(name="nt" if windows else "posix"))
    monkeypatch.setattr(cli_release_runtime, "WINDOWS", windows)
    generation = tmp_path / "release"
    root = generation / "tools" / "yoke-cli"
    assert cli_release_runtime.release_python(generation) == layout.venv_python(root, name="python3")
    scripts = root / ("Scripts" if windows else "bin")
    assert layout.venv_console_script(root, "yoke") == scripts / ("yoke.exe" if windows else "yoke")
    assert layout.venv_console_script(root, "yoke", windows_suffix=".cmd") == scripts / ("yoke.cmd" if windows else "yoke")


def test_real_venv_interpreter_and_site_packages(tmp_path):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path)], check=True)
    site = layout.venv_site_packages(tmp_path)
    assert site.is_dir()
    (site / "venv_layout_probe.py").write_text("VALUE = 37\n")
    result = subprocess.check_output(
        [str(layout.venv_python(tmp_path)), "-I", "-c", "import venv_layout_probe; print(venv_layout_probe.VALUE)"],
        text=True,
    )
    assert result.strip() == "37"


def test_windows_launcher_install_refuses_before_side_effects(monkeypatch, capsys):
    from yoke_core.tools import install_yoke_launcher as installer

    monkeypatch.setattr(installer, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(installer, "verify_python_version", lambda: pytest.fail("install started"))
    assert installer.main([]) == 2
    refusal = capsys.readouterr().err
    assert "posix_launcher_shim_unsupported" in refusal
    assert "public Windows installer" in refusal
    assert "Traceback" not in refusal


def test_product_smoke_environment_uses_native_paths_and_disposable_home(tmp_path):
    import os
    from tests.import_graph.onboard_wheel_smoke_support import _product_env

    home = tmp_path / "home"
    root = tmp_path / "venv"
    env = _product_env(home / ".yoke", root)
    assert env["PATH"].split(os.pathsep)[0] == str(layout.venv_scripts(root))
    assert env["USERPROFILE"] == env["HOME"] == str(home)
    assert env["APPDATA"] == str(home / "AppData" / "Roaming")
    assert "PYTHONPATH" not in env
    if os.name == "nt":
        assert env["SYSTEMROOT"] == os.environ["SYSTEMROOT"]

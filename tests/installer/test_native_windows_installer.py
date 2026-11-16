"""Windows bootstrap policy, including refusals before network or writes."""

import io
import subprocess
import sys
from pathlib import Path

import pytest

from public_installer_helpers import load_installer


def test_native_python_floor_refuses_before_resolution(monkeypatch):
    module = load_installer()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.sys, "version_info", (3, 11, 9))
    with pytest.raises(module.InstallError, match="windows_python_floor.*3.12"):
        module.require_native_windows_python()
    monkeypatch.setattr(module.sys, "version_info", (3, 12, 0))
    module.require_native_windows_python()


def test_windows_cli_floor_refuses_before_router(monkeypatch, capsys):
    from yoke_cli import main

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    assert main.main(["status"]) == 1
    assert "windows_python_floor" in capsys.readouterr().err


def test_long_paths_only_refuse_when_needed(monkeypatch, tmp_path):
    module = load_installer()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "windows_long_paths_enabled", lambda: False)
    module.require_windows_path(tmp_path / "short")
    with pytest.raises(
        module.InstallError, match="LongPathsEnabled=1.*restart Windows"
    ):
        module.require_windows_path(tmp_path / ("x" * 260))
    monkeypatch.setattr(module, "windows_long_paths_enabled", lambda: True)
    module.require_windows_path(tmp_path / ("x" * 260))


def test_uv_long_path_error_names_windows_recovery(monkeypatch):
    module = load_installer()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module, "windows_long_paths_enabled", lambda: False)
    with pytest.raises(module.InstallError, match="windows_long_paths_disabled"):
        module.refuse_windows_path_failure(
            subprocess.CompletedProcess([], 1, "", "os error 206")
        )


def test_wsl_choice_does_not_install(capsys):
    module = load_installer()
    with pytest.raises(SystemExit) as stopped:
        module.parse_args(["--wsl"])
    assert stopped.value.code == 0
    assert "open Ubuntu" in capsys.readouterr().err


def test_candidate_uses_native_windows_venv(monkeypatch, tmp_path):
    module = load_installer()
    monkeypatch.setattr(module.sys, "platform", "win32")
    assert (
        module.candidate_python(tmp_path)
        == tmp_path / "tools/yoke-cli/Scripts/python.exe"
    )
    output = io.StringIO()
    installer = module.Installer(module.parse_args(["--no-setup"]), stdout=output)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path))
    assert next(installer._installed_yoke_candidates()) == str(tmp_path / "yoke.cmd")


def test_bootstrap_creates_pending_generation_under_shared_publication_lock(
    monkeypatch, tmp_path
):
    module = load_installer()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, str(tmp_path), ""),
    )

    def install(command, env, root, generation, version):
        assert generation.parent == root / "releases"
        assert (generation / "pending").is_file()
        assert (root / "publication.lock").is_file()
        if sys.platform == "win32":
            with pytest.raises(PermissionError):
                generation.rename(generation.with_name("unsafe-retirement"))
        else:
            import fcntl

            with (generation / "lease").open("a+") as lease:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return subprocess.CompletedProcess(command, 1, "", "candidate refused")

    monkeypatch.setattr(module, "_install_candidate", install)
    result = module._run_isolated_install(
        ["uv", "tool", "install", "yoke-cli==1.2.3"], {}
    )
    assert result.returncode == 1
    generation = next((tmp_path / "yoke-cli-releases/releases").iterdir())
    assert (generation / "pending").is_file()
    # The failure has closed its lease so later shared-runtime cleanup can retire it.
    generation.rename(generation.with_name("retired"))


@pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell language modes require Windows"
)
def test_constrained_language_refuses_with_no_iex_recovery():
    shim = (
        Path(__file__).resolve().parents[2] / "packaging/public-installer/install.ps1"
    )
    command = (
        "$ExecutionContext.SessionState.LanguageMode = 'ConstrainedLanguage'; & '"
        + str(shim)
        + "'"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "installer_language_mode" in result.stderr
    assert (
        "uv run --isolated --no-project --python 3.12 python install.py"
        in result.stderr
    )

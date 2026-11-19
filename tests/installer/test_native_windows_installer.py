"""Windows bootstrap policy, including refusals before network or writes."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from public_installer_helpers import load_installer

pytestmark = pytest.mark.windows


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
    from yoke_cli.config import cli_release_runtime

    real_mkdtemp = module.tempfile.mkdtemp

    def create_generation(*args, **kwargs):
        lock = tmp_path / "yoke-cli-releases/publication.lock"
        with pytest.raises(BlockingIOError):
            with cli_release_runtime.locked(lock, nonblocking=True):
                pytest.fail("generation creation must exclude the release collector")
        return real_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "mkdtemp", create_generation)
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


def test_bootstrap_publication_timeout_names_recovery(monkeypatch, tmp_path, capsys):
    module = load_installer()
    ticks = iter([0, 31])
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    def contended(_descriptor):
        raise BlockingIOError("held")

    with pytest.raises(module.InstallError, match="cli_publication_busy.*retry"):
        with module._bootstrap_publication(
            tmp_path, {"acquire_exclusive_nonblocking": contended}
        ):
            pytest.fail("a contended publication lock must not admit creation")
    assert "gives up after 30 seconds" in capsys.readouterr().err


def test_windows_helper_permission_refusal_never_requests_posix_cache_repair(
    monkeypatch, tmp_path, capsys
):
    from yoke_cli.config import github_git_credential_bundle as bundle

    source = tmp_path / "helper.py"
    source.write_text("# helper\n")
    source.chmod(0o666)
    monkeypatch.setattr(bundle, "_bundle_sources", lambda: [(source, "helper.py")])

    def refuse(_path):
        raise bundle.GitHubCredentialBundleError("Windows source ACL refused")

    monkeypatch.setattr(bundle, "_safe_read_source", refuse)
    check = load_installer().HELPER_SOURCE_CHECK
    monkeypatch.setitem(
        sys.modules, "os", SimpleNamespace(name="nt", lstat=os.lstat, path=os.path)
    )
    exec(check, {})
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["unsafe_permissions"] == []
    assert "Windows source ACL refused" in verdict["refusal"]


@pytest.mark.windows_only(reason='PowerShell language modes require Windows')
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


SHIM = Path(__file__).resolve().parents[2] / "packaging/public-installer/install.ps1"
UNTRUSTED_UV = (
    "@echo off\r\n"
    ">>\"%FAKE_UV_LOG%\" echo %*\r\n"
    "if \"%FAKE_UV_MODE%\"==\"ok\" if \"%1 %2\"==\"python find\" (echo 3.12.16 & exit /b 0)\r\n"
    "if \"%FAKE_UV_MODE%\"==\"ok\" exit /b 0\r\n"
    "if \"%FAKE_UV_MODE%\"==\"other\" (echo error: network unreachable 1>&2 & exit /b 2)\r\n"
    "echo  Downloaded cpython-3.12.16-windows-x86_64-none\r\n"
    "echo error: Failed to create Python minor version link directory 1>&2\r\n"
    "echo   cause: The path cannot be traversed because it contains an untrusted"
    " mount point. (os error 448) 1>&2\r\n"
    "exit /b 2\r\n"
)


def test_shim_pins_the_uv_version_ci_uses():
    shim = SHIM.read_text(encoding="utf-8")
    pyproject = (SHIM.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    pinned = shim.split("$uvVersion = '", 1)[1].split("'", 1)[0]
    assert f'"uv=={pinned}"' in pyproject
    assert '"https://astral.sh/uv/$uvVersion/install.ps1"' in shim
    assert "https://astral.sh/uv/install.ps1" not in shim


def _run_shim(tmp_path, mode):
    import http.server
    import threading

    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/install.py").write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/uv.cmd").write_text(UNTRUSTED_UV, encoding="ascii")
    handler = lambda *a: http.server.SimpleHTTPRequestHandler(  # noqa: E731
        *a, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        env = dict(
            os.environ,
            FAKE_UV_MODE=mode,
            FAKE_UV_LOG=str(tmp_path / "uv-calls.log"),
            PATH=str(tmp_path / "bin") + os.pathsep + os.environ["PATH"],
            YOKE_INSTALL_BASE_URL=f"http://127.0.0.1:{server.server_port}",
        )
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-File", str(SHIM), "--yes"],
            capture_output=True, text=True, env=env, timeout=120,
        )
    finally:
        server.shutdown()


@pytest.mark.windows_only(reason="install.ps1 runs only in Windows PowerShell")
@pytest.mark.parametrize(
    "mode,code",
    [
        ("untrusted", "windows_untrusted_mount_point"),
        ("other", "python_bootstrap_failed"),
        ("ok", None),
    ],
)
def test_shim_reads_uv_python_preparation(tmp_path, mode, code):
    result = _run_shim(tmp_path, mode)
    output = result.stdout + result.stderr
    if code is None:
        assert result.returncode == 0, output
        calls = (tmp_path / "uv-calls.log").read_text(encoding="ascii").splitlines()
        assert calls[0] == "python find --no-project --show-version 3.12"
        runs = [call for call in calls if call.startswith("run ")]
        assert runs and all(
            call.startswith("run --isolated --no-project --python 3.12.16 python ")
            for call in runs
        )
        return
    assert result.returncode != 0
    assert code in output
    assert "yoke_install_failed" not in output
    if code == "windows_untrusted_mount_point":
        assert "https://github.com/astral-sh/uv/issues/19616" in output
        assert "local PowerShell" in output

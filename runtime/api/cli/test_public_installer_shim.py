from __future__ import annotations

import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SHIM = REPO_ROOT / "packaging" / "public-installer" / "install"
INSTALL_PY = REPO_ROOT / "packaging" / "public-installer" / "install.py"


def test_file_invocation_accepts_piped_uv_consent(tmp_path: Path) -> None:
    env = _installer_env(tmp_path, with_fake_curl=True)

    result = subprocess.run(
        ["/bin/sh", str(INSTALL_SHIM)],
        input="y\n",
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    # Cold-start copy: the consent names uv/uvx together; on success with no
    # `yoke` on PATH yet, the shim prints the resume command (no separate gate).
    assert "Yoke's only prerequisite — uv/uvx — isn't installed yet." in result.stdout
    assert (
        "Run yoke onboard to finish setting up your machine & projects."
        in result.stdout
    )
    assert "Start Yoke onboarding" not in result.stdout
    assert "/dev/tty" not in result.stderr


def test_pipe_invocation_without_yes_fails_without_tty_noise(
    tmp_path: Path,
) -> None:
    env = _installer_env(tmp_path, with_fake_curl=True)

    result = subprocess.run(
        ["/bin/sh"],
        input=INSTALL_SHIM.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 1
    # The friendly decline/failure screen now renders to stdout; stderr stays
    # clean of tty noise on the curl|bash (stdin-piped) path.
    assert "uv/uvx is required to install Yoke." in result.stdout
    assert "Device not configured" not in result.stderr


def test_python_helper_honors_plain_glyph_env(monkeypatch) -> None:
    install_py = _load_install_py()
    version = "1.2.3"
    output = io.StringIO()
    runner = _InstallPyRunner(version)
    monkeypatch.setenv("YOKE_INSTALL_FORCE_COLOR", "1")
    monkeypatch.setenv("YOKE_INSTALL_FORCE_PLAIN", "1")

    installer = install_py.Installer(
        install_py.InstallOptions(
            channel="latest",
            version=version,
            yes=True,
            dry_run=False,
            base_url="https://api.example.test",
            no_onboard=True,
        ),
        runner=runner,
        which=lambda name: "/tmp/yoke" if name == "yoke" else None,
        stdout=output,
    )

    installer.run()

    text = output.getvalue()
    assert "* Setting up Yoke" in text
    assert "* Yoke v1.2.3 is ready" in text
    assert install_py.GUTTER_ICON not in text


def test_python_helper_prefers_uv_tool_bin_dir_for_installed_yoke(
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_py = _load_install_py()
    bin_dir = tmp_path / "uv-bin"
    bin_dir.mkdir()
    yoke = bin_dir / "yoke"
    yoke.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke.chmod(0o755)
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(bin_dir))

    installer = install_py.Installer(
        install_py.InstallOptions(
            channel="latest",
            version="1.2.3",
            yes=True,
            dry_run=False,
            base_url="https://api.example.test",
            no_onboard=True,
        ),
        which=lambda name: "/ambient/yoke" if name == "yoke" else None,
        stdout=io.StringIO(),
    )

    assert installer._resolve_installed_yoke_bin() == str(yoke)  # noqa: SLF001


def _installer_env(tmp_path: Path, *, with_fake_curl: bool) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if with_fake_curl:
        _write_fake_curl(bin_dir / "curl")
    _write_helper(tmp_path / "server")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["YOKE_INSTALL_BASE_URL"] = (tmp_path / "server").as_uri()
    return env


class _InstallPyRunner:
    def __init__(self, version: str) -> None:
        self.version = version

    def __call__(self, command):  # noqa: ANN001, ANN204
        if command[0] == "uv":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, f"{self.version}\n", "")
        if command[1:] == ["--help"]:
            return subprocess.CompletedProcess(command, 0, "usage: yoke\n", "")
        if command[1:] == ["status", "--json"]:
            status = {
                "runtime": {
                    "package_versions": {
                        "yoke-cli": self.version,
                        "yoke-contracts": self.version,
                        "yoke-harness": self.version,
                        "yoke-core": self.version,
                    }
                },
                "issues": [{"severity": "error", "code": "config_missing"}],
                "connection": {"client_authority": "prod"},
            }
            return subprocess.CompletedProcess(command, 1, json.dumps(status), "")
        return subprocess.CompletedProcess(command, 43, "", f"unexpected: {command!r}")


def _load_install_py():
    spec = importlib.util.spec_from_file_location(
        "public_installer_install", INSTALL_PY
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_helper(root: Path) -> None:
    dist = root / "dist"
    dist.mkdir(parents=True)
    (dist / "install.py").write_text(
        "from __future__ import annotations\nprint('fake install helper ran')\n",
        encoding="utf-8",
    )


def _write_fake_curl(path: Path) -> None:
    python = shlex.quote(sys.executable)
    path.write_text(
        "#!/bin/sh\n"
        "cat <<'UV_INSTALL'\n"
        "#!/bin/sh\n"
        'mkdir -p "$HOME/.local/bin"\n'
        "cat > \"$HOME/.local/bin/uv\" <<'UV'\n"
        "#!/bin/sh\n"
        'if [ "$1" = "run" ]; then\n'
        "  shift\n"
        '  if [ "$1" = "--no-project" ]; then shift; fi\n'
        '  if [ "$1" = "python" ]; then shift; exec '
        f'{python} "$@"; fi\n'
        "fi\n"
        'if [ "$1" = "tool" ] && [ "$2" = "install" ]; then exit 0; fi\n'
        'echo "unexpected uv invocation: $*" >&2\n'
        "exit 43\n"
        "UV\n"
        'chmod +x "$HOME/.local/bin/uv"\n'
        "UV_INSTALL\n",
        encoding="utf-8",
    )
    path.chmod(0o755)

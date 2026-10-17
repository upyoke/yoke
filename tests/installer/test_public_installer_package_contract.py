from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SHIM = REPO_ROOT / "packaging" / "public-installer" / "install"
INSTALL_PY = REPO_ROOT / "packaging" / "public-installer" / "install.py"


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
            no_setup=True,
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
    assert sum(command[1:] == ["wsl", "setup"] for command in runner.commands) == 1


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
            no_setup=True,
        ),
        which=lambda name: "/ambient/yoke" if name == "yoke" else None,
        stdout=io.StringIO(),
    )

    assert installer._resolve_installed_yoke_bin() == str(yoke)  # noqa: SLF001


def test_product_audit_rejects_missing_hook_runtime_package() -> None:
    install_py = _load_install_py()

    with pytest.raises(install_py.InstallError, match="yoke-harness"):
        install_py._verify_product_package_presence(
            {  # noqa: SLF001
                "package_versions": {
                    "yoke-cli": "1.2.3",
                    "yoke-contracts": "1.2.3",
                    "yoke-harness": "",
                    "yoke-core": "1.2.3",
                }
            }
        )


class _InstallPyRunner:
    def __init__(self, version: str) -> None:
        self.version = version
        self.commands: list[list[str]] = []

    def __call__(self, command):  # noqa: ANN001, ANN204
        self.commands.append(list(command))
        if command[0] == "uv":
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, f"{self.version}\n", "")
        if command[1:] == ["--help"]:
            return subprocess.CompletedProcess(command, 0, "usage: yoke\n", "")
        if command[1:4] == ["settings", "set", "distribution"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["wsl", "setup"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1:] == ["hook", "resident", "restart"]:
            return subprocess.CompletedProcess(command, 0, "Hook evaluator: ready", "")
        if command[1:] == ["ui", "restart-running", "--json"]:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"ok": True, "restarted": False}), ""
            )
        if command[1:] == ["github", "credential-helper", "refresh", "--json"]:
            # Every install.py completion calls this unconditionally; nothing
            # is configured to repair on this fixture machine.
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"configured": False, "repaired": False}), ""
            )
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

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = REPO_ROOT / "packaging" / "public-installer" / "install.py"
INSTALL_SHIM_PATH = REPO_ROOT / "packaging" / "public-installer" / "install"


def load_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "yoke_public_installer_machine_prereqs",
        INSTALLER_PATH,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def options(installer_mod: ModuleType):
    return installer_mod.InstallOptions(
        channel="stable",
        version=None,
        yes=False,
        dry_run=False,
        base_url="https://api.upyoke.com",
        no_onboard=False,
    )


class RecordingRunner:
    def __init__(
        self,
        *,
        rc: int = 0,
        stdout: str = "",
        stderr: str = "",
        responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.responses = responses or {}

    def __call__(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(command)
        self.commands.append(argv)
        override = self.responses.get(tuple(argv))
        if override is not None:
            return override
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


def _installed_runtime() -> dict[str, object]:
    return {
        "package_versions": {
            package: "1.2.3"
            for package in (
                "yoke-cli",
                "yoke-contracts",
                "yoke-harness",
                "yoke-core",
            )
        },
    }


def test_no_node_npm_or_git_prerequisite_in_helper_or_shim() -> None:
    # uv owns Python; git, Node.js, npm, and the browser runtime are deferred to
    # the moment they are needed. Neither the helper nor the shim may probe them.
    # Homebrew is the EXCEPTION: on macOS it is offered as an optional `uv/uvx`
    # install path (never required — it falls back to the Astral installer), so
    # it is intentionally allowed; the Linux package managers stay banned because
    # the shim installs uv via the official Astral installer, not apt/dnf.
    helper = INSTALLER_PATH.read_text(encoding="utf-8")
    shim = INSTALL_SHIM_PATH.read_text(encoding="utf-8")
    for surface in (helper, shim):
        for absent in ("python3.1", "venv", "wheelhouse", "apt-get", "dnf"):
            assert absent not in surface.lower(), f"unexpected prerequisite mechanic: {absent}"
    # The browser runtime is never set up at install time (deferred to first use).
    for surface in (helper, shim):
        assert "qa browser setup" not in surface.lower()
        assert "browser-runtime" not in surface.lower()
        assert "browser_runtime" not in surface.lower()


def test_helper_does_not_probe_local_core_runtime() -> None:
    installer_mod = load_installer()
    checked: list[str] = []

    def which(name: str) -> str | None:
        checked.append(name)
        if name in {"docker", "colima"}:
            raise AssertionError(f"unexpected local-core runtime probe: {name}")
        return f"/bin/{name}"

    installer = installer_mod.Installer(options(installer_mod), which=which)
    installer._advise_path()

    assert checked == ["yoke"]
    shim = INSTALL_SHIM_PATH.read_text(encoding="utf-8")
    assert "docker" not in shim
    assert "colima" not in shim


def test_smoke_runs_version_and_help() -> None:
    installer_mod = load_installer()
    runner = RecordingRunner(
        stdout="0.2.0\n",
    )
    installer = installer_mod.Installer(options(installer_mod), runner=runner)

    installer._smoke_yoke()

    assert runner.commands == [
        ["yoke", "--version"],
        ["yoke", "--help"],
    ]


def test_smoke_failure_is_user_actionable() -> None:
    installer_mod = load_installer()
    runner = RecordingRunner(rc=2, stderr="yoke: command not found")
    installer = installer_mod.Installer(options(installer_mod), runner=runner)

    with pytest.raises(installer_mod.InstallError) as exc_info:
        installer._smoke_yoke()

    assert "yoke --version" in str(exc_info.value)
    assert "yoke: command not found" in str(exc_info.value)


def test_product_boundary_audit_passes_for_clean_product_status() -> None:
    installer_mod = load_installer()
    status_ok = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        0,
        json.dumps(
            {
                "runtime": _installed_runtime(),
                "connection": {"client_authority": "api"},
            }
        ),
        "",
    )
    runner = RecordingRunner(
        responses={("yoke", "status", "--json"): status_ok}
    )
    installer = installer_mod.Installer(options(installer_mod), runner=runner)

    installer._product_boundary_audit()

    assert runner.commands == [["yoke", "status", "--json"]]


def test_product_boundary_audit_accepts_fresh_machine_status() -> None:
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        1,
        json.dumps(
            {
                "ok": False,
                "runtime": _installed_runtime(),
                "connection": {"client_authority": "api"},
                "issues": [
                    {"code": "config_missing", "severity": "error"},
                    {"code": "schema_version", "severity": "error"},
                    {"code": "connections_required", "severity": "error"},
                    {"code": "active_env_required", "severity": "error"},
                    {"code": "active_env", "severity": "error"},
                    {"code": "temp_root_not_writable", "severity": "error"},
                    {"code": "cache_dir_not_writable", "severity": "error"},
                    {"code": "project_mapping_missing", "severity": "warning"},
                ],
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(options(installer_mod), runner=runner)

    installer._product_boundary_audit()

    assert runner.commands == [["yoke", "status", "--json"]]


def test_product_boundary_audit_rejects_unexpected_status_error() -> None:
    installer_mod = load_installer()
    status = subprocess.CompletedProcess(
        ["yoke", "status", "--json"],
        1,
        json.dumps(
            {
                "runtime": {},
                "connection": {"client_authority": "api"},
                "issues": [{"code": "database_corrupt", "severity": "error"}],
            }
        ),
        "",
    )
    runner = RecordingRunner(responses={("yoke", "status", "--json"): status})
    installer = installer_mod.Installer(options(installer_mod), runner=runner)

    try:
        installer._product_boundary_audit()
    except installer_mod.InstallError as exc:
        assert "unexpected errors" in str(exc)
        assert "database_corrupt" in str(exc)
    else:
        raise AssertionError("expected product-boundary audit failure")

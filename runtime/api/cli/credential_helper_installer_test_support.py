"""Real installer and git credential-helper fixtures for entry-point tests."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType

import pytest

from runtime.api.cli.test_github_stable_helper_runtime import (
    _write_refresh_sitecustomize,
)
from runtime.api.cli import github_stable_helper_test_support as helper_support
from yoke_cli.config import (
    distribution,
    github_git_credentials,
    github_repo_helper_reconnect,
)
from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL

INSTALLER_PATH = (
    Path(__file__).resolve().parents[3]
    / "packaging"
    / "public-installer"
    / "install.py"
)


def _load_installer(name: str, source_bytes: bytes) -> ModuleType:
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".py", delete=False) as handle:
        handle.write(source_bytes)
        path = handle.name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configured_repo_with_wiped_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    token: str,
) -> tuple[Path, Path, Path]:
    """A real registered checkout with a real helper bundle, wiped the way
    `uv tool install --reinstall --force` wipes it."""
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    helper_support.run_git(repo, "init")
    token_file = home / "secrets" / f"github-app-user-{'a' * 32}.json"
    config = tmp_path / "config.json"
    helper_support.write_github_app_config(config, token_file, token)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["connections"]["local"] = {
        "transport": "https",
        "prod": False,
        "api_url": "https://yoke.example.test",
        "credential_source": {"kind": "token_file", "path": str(token_file)},
    }
    payload["projects"] = [{"checkout": str(repo), "project_id": 1, "env": "local"}]
    config.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))
    distribution.save(origin=DISTRIBUTION_PROD_URL, channel="stable", path=config)
    site = tmp_path / "site"
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)
    github_git_credentials.configure_repo_helper(repo, config_path=config)
    helper_path = site / github_git_credentials.STABLE_HELPER_FILE_NAME
    assert helper_path.is_file()
    shutil.rmtree(site)
    assert not helper_path.is_file()
    return repo, config, site


def _isolated_yoke_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Give ``yoke`` binary resolution a deterministic candidate, isolated
    from whatever real launcher this dev machine happens to have on disk."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    yoke_bin = bin_dir / "yoke"
    yoke_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    yoke_bin.chmod(0o755)
    monkeypatch.setenv("XDG_BIN_HOME", str(bin_dir))
    return str(yoke_bin)


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, token: str
) -> tuple[Path, Path, Path, str]:
    repo, config, site = _configured_repo_with_wiped_bundle(
        tmp_path, monkeypatch, token=token
    )
    yoke_bin = _isolated_yoke_bin(tmp_path, monkeypatch)
    return repo, config, site, yoke_bin


def _in_process_repair_runner(config: Path, yoke_bin: str):
    """Stand in for the freshly installed binary: routes the installer's own
    `github credential-helper refresh --json` call to the real production
    repair function in-process, and stubs only the surrounding uv/version/
    status boundary -- the same substitution every installer test uses."""

    def run(command):
        cmd = list(command)
        if cmd[:3] == ["uv", "tool", "install"]:
            return subprocess.CompletedProcess(cmd, 0, "+ yoke-cli==2.0.0", "")
        if cmd[:3] == ["uv", "tool", "dir"]:
            # Unresolved on purpose: falls through to the injected `which`.
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if cmd == [yoke_bin, "--version"]:
            return subprocess.CompletedProcess(cmd, 0, "2.0.0\n", "")
        if cmd == [yoke_bin, "--help"]:
            return subprocess.CompletedProcess(cmd, 0, "help", "")
        if cmd == [yoke_bin, "status", "--json"]:
            versions = {
                p: "2.0.0"
                for p in ("yoke-cli", "yoke-contracts", "yoke-harness", "yoke-core")
            }
            payload = json.dumps(
                {
                    "runtime": {"package_versions": versions},
                    "connection": {"client_authority": "api"},
                }
            )
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if cmd == [yoke_bin, "github", "credential-helper", "refresh", "--json"]:
            result = github_repo_helper_reconnect.restore_missing_bundle(config)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(result), "")
        if cmd[:4] == [yoke_bin, "config", "distribution", "set"]:
            result = distribution.save(
                origin=cmd[cmd.index("--origin") + 1],
                channel=cmd[cmd.index("--channel") + 1],
                path=config,
            )
            return subprocess.CompletedProcess(cmd, 0, json.dumps(result), "")
        raise AssertionError(f"unexpected installer command: {cmd}")

    return run


def _run_real_installer(
    *,
    config: Path,
    yoke_bin: str,
    name: str,
    source_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    """Load and run the real install.py, mimicking `main()`'s own
    ``InstallError`` handling -- exactly what the real `curl | sh` /
    subprocess boundary does -- so a genuine repair failure surfaces the
    same way a real installer subprocess failure would."""
    installer_mod = _load_installer(name, source_bytes or INSTALLER_PATH.read_bytes())
    options = installer_mod.InstallOptions(
        channel="stable",
        version="2.0.0",
        yes=True,
        dry_run=False,
        base_url=DISTRIBUTION_PROD_URL,
        no_onboard=True,
    )
    out = io.StringIO()
    installer = installer_mod.Installer(
        options,
        runner=_in_process_repair_runner(config, yoke_bin),
        which=lambda _name: yoke_bin,
        stdout=out,
    )
    try:
        installer.run()
    except installer_mod.InstallError as exc:
        return subprocess.CompletedProcess(("installer",), 1, out.getvalue(), str(exc))
    return subprocess.CompletedProcess(("installer",), 0, out.getvalue(), "")


def _assert_git_helper_works(repo: Path, tmp_path: Path, token: str) -> None:
    hooks = tmp_path / "python-hooks"
    _write_refresh_sitecustomize(hooks, token)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(hooks)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    filled = subprocess.run(
        ["git", "credential", "fill"],
        cwd=repo,
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        env=env,
    )
    assert "username=x-access-token" in filled.stdout
    assert f"password={token}" in filled.stdout

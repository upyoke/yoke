"""Both real entry points -- the public installer's own completion, and
`yoke update` running that same installer -- repair a wiped git
credential-helper bundle through the real repair function, never a mocked
outcome, and a real repair failure fails both entry points too. Success is
proven with an ordinary `git credential fill` against fixture credentials.
"""

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
from yoke_cli.config import github_git_credentials, github_repo_helper_reconnect
from yoke_cli.config import self_update
from yoke_cli.self_host import release_target
from yoke_contracts.server_image import pinned_server_image

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
    payload["projects"] = [{"checkout": str(repo), "project_id": 1, "env": "local"}]
    config.write_text(json.dumps(payload), encoding="utf-8")
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
        base_url="https://api.upyoke.com",
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


def test_public_installer_completion_repairs_bundle_and_git_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "installer-repair-secret"
    repo, config, site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)

    completed = _run_real_installer(
        config=config,
        yoke_bin=yoke_bin,
        name="yoke_installer_repair_entry_point",
    )

    assert completed.returncode == 0
    assert (site / github_git_credentials.STABLE_HELPER_FILE_NAME).is_file()
    assert "Rebuilt the git credential helper bundle" in completed.stdout
    _assert_git_helper_works(repo, tmp_path, token)


def test_public_installer_completion_fails_when_repair_genuinely_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real repair failure (the bundle write itself fails) must fail the
    installer -- readiness requires the repair to have completed, not
    merely been attempted."""
    token = "installer-failure-secret"
    _repo, config, _site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    monkeypatch.setattr(
        github_git_credentials,
        "install_stable_helper",
        lambda *_a, **_k: (_ for _ in ()).throw(
            github_git_credentials.GitHubCredentialBundleError("disk full")
        ),
    )

    completed = _run_real_installer(
        config=config,
        yoke_bin=yoke_bin,
        name="yoke_installer_repair_failure",
    )

    assert completed.returncode != 0
    assert "credential helper repair failed" in completed.stderr
    assert "disk full" in completed.stderr
    # The friendly stdout screen never reaches the "ready" completion state
    # a caller could mistake for success.
    assert "Rebuilt the git credential helper bundle" not in completed.stdout


def _stub_update_through_real_installer(
    *,
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    yoke_bin: str,
    installer_module_name: str,
) -> None:
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": "packaged_wheel",
            "checkout_root": None,
            "module_origin": "/wherever/yoke_cli/__init__.py",
            "version": "0.1.1+launch.433",
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _name: yoke_bin)
    source_commit = "4" * 40
    target = release_target.ReleaseTarget(
        version="2.0.0",
        source_commit=source_commit,
        image=pinned_server_image(source_commit),
        base_url="https://api.upyoke.com",
        channel="stable",
        installer_url="https://api.upyoke.com/dist/install.py",
    )
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **_k: target,
    )
    monkeypatch.setattr(
        self_update.release_target,
        "fetch_installer",
        lambda _target: INSTALLER_PATH.read_bytes(),
    )
    monkeypatch.setattr(
        self_update.release_target,
        "run_installer",
        lambda _target, installer_bytes, **_k: _run_real_installer(
            config=config,
            yoke_bin=yoke_bin,
            name=installer_module_name,
            source_bytes=installer_bytes,
        ),
    )
    monkeypatch.setattr(
        self_update,
        "_RUN",
        lambda command, **_k: subprocess.CompletedProcess(command, 0, "2.0.0\n", ""),
    )


def test_yoke_update_runs_the_real_installer_and_git_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "update-repair-secret"
    repo, config, site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    _stub_update_through_real_installer(
        monkeypatch=monkeypatch,
        config=config,
        yoke_bin=yoke_bin,
        installer_module_name="yoke_installer_repair_via_update",
    )

    result = self_update.run_update()

    # A successful reinstall carries no independent repair signal: the
    # installer performed and enforced the repair itself.
    assert result["credential_helper_configured"] is None
    assert result["credential_helper_repaired"] is None
    assert result["credential_helper_error"] is None
    assert (site / github_git_credentials.STABLE_HELPER_FILE_NAME).is_file()
    _assert_git_helper_works(repo, tmp_path, token)


def test_yoke_update_surfaces_a_real_installer_repair_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same real repair failure the installer entry point fails on must
    also reach `yoke update` as a real failure, not silent success."""
    token = "update-failure-secret"
    _repo, config, _site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    monkeypatch.setattr(
        github_git_credentials,
        "install_stable_helper",
        lambda *_a, **_k: (_ for _ in ()).throw(
            github_git_credentials.GitHubCredentialBundleError("disk full")
        ),
    )
    _stub_update_through_real_installer(
        monkeypatch=monkeypatch,
        config=config,
        yoke_bin=yoke_bin,
        installer_module_name="yoke_installer_repair_failure_via_update",
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "credential helper repair failed" in str(raised.value)
    assert "disk full" in str(raised.value)

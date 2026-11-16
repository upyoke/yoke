"""Yoke's Git credential helper runs under the real Git and coexists with GCM.

Git Credential Manager (the Git for Windows default) installs a global
``credential.helper``. Yoke resets only the GitHub URL's chain in the
checkout, so GitHub pushes use Yoke's token and every other host keeps GCM,
whichever was installed first. These tests drive the ``git`` on PATH; on the
Windows CI job that is Git for Windows, which runs ``!`` helpers through its
bundled shell.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from runtime.api.cli.github_stable_helper_runtime_test_support import (
    _write_refresh_sitecustomize,
)
from runtime.api.cli.github_stable_helper_test_support import (
    write_github_app_config,
)
from yoke_cli.config import github_git_credentials

TOKEN = "yoke-helper-secret"
# Stands in for `credential.helper=manager`; a shell function works under
# Git for Windows' sh as well as POSIX shells.
FAKE_GCM = "!f() { echo username=gcm-user; echo password=gcm-secret; }; f"


def _git(root: Path, global_config: Path, *args: str, stdin: str | None = None) -> str:
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_GLOBAL=str(global_config),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
    )
    return subprocess.run(
        ["git", *args],
        cwd=root,
        input=stdin,
        text=True,
        capture_output=True,
        check=True,
        env=env,
        timeout=60,
    ).stdout


def _fill(root: Path, global_config: Path, host: str) -> dict[str, str]:
    output = _git(
        root,
        global_config,
        "credential",
        "fill",
        stdin=f"protocol=https\nhost={host}\n\n",
    )
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "repo"
    root.mkdir()
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text("", encoding="utf-8")
    _git(root, global_config, "init", "-q")
    token_file = (
        Path(os.environ["YOKE_MACHINE_HOME"]) / "secrets" / f"github-app-user-{'b' * 32}.json"
    )
    config = tmp_path / "config.json"
    write_github_app_config(config, token_file, TOKEN)
    hooks = tmp_path / "python-hooks"
    _write_refresh_sitecustomize(hooks, TOKEN)
    monkeypatch.setenv("PYTHONPATH", str(hooks))
    site = tmp_path / "site"
    monkeypatch.setattr(github_git_credentials, "_helper_dir", lambda: site)
    return root, global_config, config


def _install_gcm(global_config: Path, root: Path) -> None:
    _git(root, global_config, "config", "--global", "credential.helper", FAKE_GCM)


def _configure_yoke(root: Path, config: Path) -> None:
    result = github_git_credentials.configure_repo_helper(root, config_path=config)
    assert result["configured"] is True, result


@pytest.mark.parametrize("gcm_first", [True, False], ids=["gcm-then-yoke", "yoke-then-gcm"])
def test_github_uses_yoke_and_other_hosts_keep_gcm(checkout, gcm_first: bool) -> None:
    root, global_config, config = checkout
    if gcm_first:
        _install_gcm(global_config, root)
        _configure_yoke(root, config)
    else:
        _configure_yoke(root, config)
        _install_gcm(global_config, root)

    github = _fill(root, global_config, "github.com")
    other = _fill(root, global_config, "dev.azure.com")

    assert (github["username"], github["password"]) == ("x-access-token", TOKEN)
    assert (other["username"], other["password"]) == ("gcm-user", "gcm-secret")
    assert TOKEN not in (root / ".git" / "config").read_text(encoding="utf-8")
    assert "gcm" not in (root / ".git" / "config").read_text(encoding="utf-8")


def test_removing_yoke_leaves_gcm_serving_github(checkout) -> None:
    root, global_config, config = checkout
    _install_gcm(global_config, root)
    _configure_yoke(root, config)

    github_git_credentials.remove_repo_helpers(root, config_path=config)

    github = _fill(root, global_config, "github.com")
    assert (github["username"], github["password"]) == ("gcm-user", "gcm-secret")

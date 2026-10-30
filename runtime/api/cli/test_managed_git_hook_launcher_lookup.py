"""Managed git-hook shims find the `yoke` launcher or let the commit through.

Each shim runs under real ``sh`` with a scrubbed environment: the launcher
on PATH, at ``$XDG_BIN_HOME/yoke``, at ``~/.local/bin/yoke``, or nowhere.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

import pytest

from yoke_contracts.api_urls import DISTRIBUTION_STAGE_URL

from yoke_cli.project_install.managed_git_hooks import (
    render_git_hook,
    POST_CHECKOUT_SHIM,
    POST_COMMIT_SHIM,
    POST_MERGE_SHIM,
    POST_REWRITE_SHIM,
    PRE_COMMIT_SHIM,
    PRE_MERGE_COMMIT_SHIM,
)

SHIMS = {
    "pre-commit": (PRE_COMMIT_SHIM, "git pre-commit"),
    "post-commit": (POST_COMMIT_SHIM, "git post-commit"),
    "pre-merge-commit": (PRE_MERGE_COMMIT_SHIM, "git pre-commit"),
    "post-merge": (POST_MERGE_SHIM, "git post-merge"),
    "post-rewrite": (POST_REWRITE_SHIM, "git post-rewrite"),
    "post-checkout": (POST_CHECKOUT_SHIM, "git post-checkout"),
}
SYSTEM_PATH = "/usr/bin:/bin"


@pytest.fixture(autouse=True)
def stage_distribution(monkeypatch):
    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", DISTRIBUTION_STAGE_URL)


def _fake_launcher(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / "yoke"
    launcher.write_text(f'#!/bin/sh\necho "{directory} $*"\nexit 3\n')
    launcher.chmod(0o755)
    return launcher


def _run(tmp_path: Path, shim: str, env: dict[str, str]):
    hook = tmp_path / "hook"
    hook.write_text(render_git_hook(shim))
    return subprocess.run(
        ["sh", str(hook), "extra"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("hook_name", sorted(SHIMS))
class TestLauncherLookup:
    def test_launcher_on_path_wins(self, tmp_path, hook_name):
        shim, subcommand = SHIMS[hook_name]
        on_path = tmp_path / "on-path"
        _fake_launcher(on_path)
        _fake_launcher(tmp_path / "home" / ".local" / "bin")
        proc = _run(
            tmp_path,
            shim,
            {
                "HOME": str(tmp_path / "home"),
                "PATH": f"{on_path}:{SYSTEM_PATH}",
            },
        )
        assert proc.returncode == 3
        assert proc.stdout.strip() == f"{on_path} {subcommand} extra"

    def test_xdg_bin_home_when_not_on_path(self, tmp_path, hook_name):
        shim, subcommand = SHIMS[hook_name]
        xdg = tmp_path / "xdg-bin"
        _fake_launcher(xdg)
        proc = _run(
            tmp_path,
            shim,
            {
                "HOME": str(tmp_path / "home"),
                "XDG_BIN_HOME": str(xdg),
                "PATH": SYSTEM_PATH,
            },
        )
        assert proc.returncode == 3
        assert proc.stdout.strip() == f"{xdg} {subcommand} extra"

    def test_default_launcher_home_when_not_on_path(self, tmp_path, hook_name):
        shim, subcommand = SHIMS[hook_name]
        home_bin = tmp_path / "home" / ".local" / "bin"
        _fake_launcher(home_bin)
        proc = _run(
            tmp_path,
            shim,
            {
                "HOME": str(tmp_path / "home"),
                "PATH": SYSTEM_PATH,
            },
        )
        assert proc.returncode == 3
        assert proc.stdout.strip() == f"{home_bin} {subcommand} extra"

    def test_missing_launcher_lets_commit_through_with_one_line(
        self,
        tmp_path,
        hook_name,
    ):
        shim, _ = SHIMS[hook_name]
        proc = _run(
            tmp_path,
            shim,
            {
                "HOME": str(tmp_path / "home"),
                "PATH": SYSTEM_PATH,
            },
        )
        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == (
            f"yoke ({hook_name}): Yoke is not installed on this computer "
            f"({platform.node()}); Yoke checks skipped. Install: "
            f"`curl -fsSL {DISTRIBUTION_STAGE_URL}/install | sh`\n"
        )


@pytest.mark.parametrize("hook_name", sorted(SHIMS))
def test_shim_carries_no_bypass_advice_or_fixed_path(hook_name):
    shim, _ = SHIMS[hook_name]
    assert "--no-verify" not in shim
    assert "/Users/" not in shim
    assert "/home/" not in shim

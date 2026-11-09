# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import copy

import json

import subprocess

import pytest

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)

from yoke_core.tools import installer_campaign_plan as sync

from yoke_core.domain.installer_campaign_plan_source import compare_plan
from yoke_core.tools.installer_campaign_plan import main

from runtime.api.domain.qa_release_channel_target_test_support import _target


@pytest.fixture
def source_checkout(tmp_path, monkeypatch):
    def git(root, *args, timeout=30):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    remote = tmp_path / "remote"
    remote.mkdir()
    assert git(remote, "init", "--bare", "--initial-branch=stable").returncode == 0
    root = tmp_path / "source"
    assert git(tmp_path, "clone", str(remote), str(root)).returncode == 0
    for key, value in (
        ("user.name", "QA Fixture"),
        ("user.email", "qa@example.invalid"),
    ):
        assert git(root, "config", key, value).returncode == 0
    (root / "cases.json").write_text("[]\n")
    assert git(root, "add", "cases.json").returncode == 0
    assert git(root, "commit", "-m", "Define cases").returncode == 0
    assert git(root, "push", "origin", "stable").returncode == 0
    assert git(root, "remote", "set-head", "origin", "--auto").returncode == 0
    monkeypatch.setattr(sync.pack_catalog, "server_tree_root", lambda: root)
    monkeypatch.setattr(sync.source_git, "git", git)
    return root, git

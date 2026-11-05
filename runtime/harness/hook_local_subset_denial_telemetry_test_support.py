# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import subprocess

import pytest

from runtime.harness.hook_project_scope_test_support import project_map as project_map

from yoke_harness.hooks import local_subset

from yoke_harness.hooks.deadline import start_hook_deadline


def _git(cwd, *args) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def dirty_repo(tmp_path, project_map):
    """A git repo with one tracked file left modified (uncommitted)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    tracked = repo / "tracked.txt"
    tracked.write_text("original\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "seed")
    tracked.write_text("modified\n")
    project_map["connection_projects"]["local"] = [
        {"checkout": str(repo), "project_id": 1}
    ]
    return repo

"""Worktree creation coverage for workflow-required lane roles."""

from __future__ import annotations

import os
import subprocess

from runtime.api.domain.test_worktree_create_multiworktree import (
    _config_path,
    seed_multiworktree_epic,
)
from yoke_core.domain.worktree import create_worktree


def test_epic_creates_integration_lane_and_each_worker(
    git_repo,
    yoke_db,
):
    branches = [
        "epic-99200-cli",
        "epic-99200-core",
        "epic-99200-tests",
    ]
    entries = seed_multiworktree_epic(
        yoke_db, 99200, branches, str(git_repo),
    )

    result = create_worktree(
        99200,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error is None, result.error
    assert result.created is True
    assert len(result.worktrees) == len(branches) + 1
    assert result.worktrees[0].lane_role == "integration"
    assert result.worktrees[0].branch == "YOK-99200"
    assert {
        entry.branch
        for entry in result.worktrees
        if entry.lane_role == "worker"
    } == set(branches)
    for branch, path in entries:
        assert os.path.isdir(path), f"missing worktree at {path}"
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        assert current.stdout.strip() == branch

    listing = subprocess.run(
        ["git", "-C", str(git_repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    for _, path in entries:
        assert path in listing.stdout
    assert result.worktrees[0].path in listing.stdout

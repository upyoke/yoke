"""HC-worktree-health names landed branches no item owns, and deletes none."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.engines.doctor_hc_unowned_branches import (
    default_branch,
    unowned_branch_issues,
    unowned_landed_branches,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main", str(root)], check=True
    )
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    # A backup branch whose work main already holds.
    _git(root, "switch", "-q", "-c", "PLAT-421-presquash")
    (root / "b.txt").write_text("b\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "work")
    _git(root, "switch", "-q", "main")
    _git(root, "merge", "-q", "--squash", "PLAT-421-presquash")
    _git(root, "commit", "-q", "-m", "squashed")
    # A branch carrying work main does not hold.
    _git(root, "switch", "-q", "-c", "side-work")
    (root / "c.txt").write_text("c\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "unlanded")
    _git(root, "switch", "-q", "main")
    # A landed branch an item records.
    _git(root, "branch", "YOK-9")
    return root


def _branches(repo: Path) -> list[str]:
    return _git(
        repo, "for-each-ref", "--format=%(refname:lstrip=2)", "refs/heads"
    ).split()


def test_an_unowned_branch_main_contains_is_reported_not_deleted(repo: Path):
    assert default_branch(str(repo)) == "main"

    issues = unowned_branch_issues(
        str(repo),
        local_branches=_branches(repo),
        owned_branches={"YOK-9"},
        checked_out={"main"},
        default_branch="main",
    )

    assert len(issues) == 1
    assert "PLAT-421-presquash" in issues[0]
    assert "PLAT-421-presquash" in _branches(repo)


def test_owned_checked_out_and_unlanded_branches_are_not_reported(repo: Path):
    _git(repo, "worktree", "add", "-q", str(repo.parent / "wt"), "PLAT-421-presquash")

    assert (
        unowned_landed_branches(
            str(repo),
            local_branches=_branches(repo),
            owned_branches={"YOK-9"},
            checked_out={"main", "PLAT-421-presquash"},
            default_branch="main",
        )
        == []
    )

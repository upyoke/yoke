"""What counts as "the target already holds this branch".

These run against real repositories because every reading is a git fact:
what ancestry says, what patch ids pair up, and which delete git's own
safety refuses. A fake that answers those cannot fail the way git does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.engines.branch_landed_evidence import (
    ANCESTOR_PROOF,
    PATCH_EQUIVALENT_PROOF,
    BranchLandedEvidence,
    assess_branch_landed,
    delete_landed_branch,
)

BRANCH = "YOK-LANDED"


def _git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-m", "base")
    _git(root, "checkout", "-b", BRANCH)
    (root / "lane.txt").write_text("lane work\n", encoding="utf-8")
    _git(root, "add", "lane.txt")
    _git(root, "commit", "-m", "lane work")
    _git(root, "checkout", "main")
    return root


def _run_git(repo: Path):
    def run(command: list[str]):
        return _git(repo, *command, check=False)

    return run


def _land_rebased(repo: Path) -> None:
    """Land the lane's change the way a rebase or squash merge does.

    Main moves first, so replaying the lane commit onto it produces a
    different commit for the same patch — exactly the history a landed
    lane is left holding, and the one exact ancestry reads as unmerged.
    """
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "later work")
    _git(repo, "cherry-pick", BRANCH)


def test_a_merged_branch_is_landed_by_ancestry(repo: Path):
    _git(repo, "merge", "--no-ff", "-m", f"merge {BRANCH}", BRANCH)

    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")

    assert evidence == BranchLandedEvidence(True, proof=ANCESTOR_PROOF)


def test_a_rebased_lane_is_landed_by_patch_equivalence(repo: Path):
    """The changes landed; the lane's own commits were rewritten to do it.

    This is what a rebase-and-merge or squash landing leaves behind, and
    exact ancestry calls it unmerged — which is why the lane outlived its
    terminal item on disk.
    """
    _land_rebased(repo)

    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")

    assert evidence.landed is True
    assert evidence.proof == PATCH_EQUIVALENT_PROOF


def test_a_branch_with_unique_work_is_not_landed(repo: Path):
    """One commit the target has no equivalent for keeps the whole branch."""
    _land_rebased(repo)
    _git(repo, "checkout", BRANCH)
    (repo / "unique.txt").write_text("not landed\n", encoding="utf-8")
    _git(repo, "add", "unique.txt")
    _git(repo, "commit", "-m", "unique work")
    _git(repo, "checkout", "main")

    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")

    assert evidence.landed is False
    assert "1 commit with no equivalent there" in evidence.reason


def test_a_merge_commit_on_the_branch_is_never_patch_equivalent(repo: Path):
    """git cherry skips merges, so no complete proof exists to read."""
    _git(repo, "checkout", "-b", "sibling", "main")
    (repo / "sibling.txt").write_text("sibling\n", encoding="utf-8")
    _git(repo, "add", "sibling.txt")
    _git(repo, "commit", "-m", "sibling work")
    _git(repo, "checkout", BRANCH)
    _git(repo, "merge", "--no-ff", "-m", "merge sibling", "sibling")
    _git(repo, "checkout", "main")

    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")

    assert evidence.landed is False
    assert "merge commit equivalence cannot prove" in evidence.reason


def test_a_rebased_branch_is_deleted_where_git_safety_refuses(repo: Path):
    """The proof this module makes is the one ``branch -d`` cannot."""
    _land_rebased(repo)
    refused = _git(repo, "branch", "-d", BRANCH, check=False)
    assert refused.returncode != 0

    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")
    refusal = delete_landed_branch(
        _run_git(repo), branch=BRANCH, evidence=evidence
    )

    assert refusal == ""
    assert BRANCH not in _git(repo, "branch", "--list", BRANCH).stdout


def test_an_unproven_branch_is_never_deleted(repo: Path):
    """Without evidence the branch stays, and the reason travels with it."""
    evidence = assess_branch_landed(_run_git(repo), branch=BRANCH, base="main")

    refusal = delete_landed_branch(
        _run_git(repo), branch=BRANCH, evidence=evidence
    )

    assert refusal == evidence.reason
    assert BRANCH in _git(repo, "branch", "--list", BRANCH).stdout

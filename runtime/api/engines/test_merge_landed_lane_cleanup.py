"""A landed lane leaves nothing behind, and an unlanded one is kept.

These run against real repositories because every proof the cleanup relies on
is a git fact: what ``origin/main`` contains after a fetch, whether a worktree
is clean, whether a branch still exists. A fake that answers those questions
cannot fail the way git does.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.engines.merge_landed_lane_cleanup import (
    prune_landed_lane,
    release_lane_row,
)

BRANCH = "YOK-CLEANUP"


def _git(path: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _run_git(args, *, cwd=None, capture=False):
    """The engine's git-runner shape, backed by a real subprocess."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def landed_lane(tmp_path: Path):
    """A repo whose lane branch is merged and pushed, with a live worktree."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        check=True, capture_output=True, text=True,
    )
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    nested = repo / "webapp"
    nested.mkdir()
    (nested / ".gitignore").write_text("generated/\n", encoding="utf-8")
    _git(repo, "add", "README.md", "webapp/.gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")

    worktree = repo / ".worktrees" / BRANCH
    _git(repo, "worktree", "add", "-b", BRANCH, str(worktree))
    (worktree / "lane.txt").write_text("lane work\n", encoding="utf-8")
    _git(worktree, "add", "lane.txt")
    _git(worktree, "commit", "-m", "lane work")
    _git(repo, "push", "origin", BRANCH)
    return SimpleNamespace(origin=origin, repo=repo, worktree=worktree)


def _land_on_main(repo: Path) -> None:
    """Merge the lane on the remote, the way a merge queue would."""
    _git(repo, "fetch", "origin", BRANCH)
    _git(repo, "merge", "--no-ff", "-m", f"merge {BRANCH}", BRANCH)
    _git(repo, "push", "origin", "main")
    _git(repo, "update-ref", "refs/heads/main", "HEAD~1")


def _remote_branches(repo: Path) -> list[str]:
    listed = _git(repo, "ls-remote", "--heads", "origin")
    return [line.split()[1] for line in listed.stdout.splitlines() if line]


def _local_branches(repo: Path) -> list[str]:
    listed = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    return listed.stdout.split()


def test_landed_lane_leaves_no_worktree_branch_or_remote(landed_lane):
    """Every part of the lane retires together once the merge is visible.

    A queue landing merges on GitHub, so nothing local removes the lane. What
    survives is a directory, a local branch, and a remote branch per landed
    item — the sweep an operator ends up doing by hand.
    """
    _land_on_main(landed_lane.repo)
    said: list[str] = []

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo),
        branch=BRANCH,
        target="main",
        run_git=_run_git,
        emit=lambda message, **_kw: said.append(message),
    )

    assert preserved == ()
    assert not landed_lane.worktree.exists()
    assert BRANCH not in _local_branches(landed_lane.repo)
    assert f"refs/heads/{BRANCH}" not in _remote_branches(landed_lane.repo)
    assert any("Deleted merged remote branch" in line for line in said)
    assert any("Pruned merged worktree" in line for line in said)
    assert any("Pruned merged local branch" in line for line in said)


def test_landed_lane_prunes_against_origin_not_the_local_target(landed_lane):
    """The proof is the fetched remote, which is where a queue merge lands.

    Local ``main`` still points at the pre-merge commit here, exactly as it
    does in a checkout that watched the queue merge remotely.
    """
    _land_on_main(landed_lane.repo)
    local_main = _git(landed_lane.repo, "rev-parse", "main").stdout.strip()
    origin_main = _git(
        landed_lane.repo, "ls-remote", "origin", "refs/heads/main",
    ).stdout.split()[0]
    assert local_main != origin_main

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        run_git=_run_git, emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not landed_lane.worktree.exists()


def test_unmerged_lane_is_preserved_with_the_reason_named(landed_lane):
    """Nothing is deleted for a branch the target does not contain."""
    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        run_git=_run_git, emit=lambda *_a, **_kw: None,
    )

    assert preserved == (
        f"lane {BRANCH} preserved: branch is not merged into origin/main",
    )
    assert landed_lane.worktree.exists()
    assert BRANCH in _local_branches(landed_lane.repo)
    assert f"refs/heads/{BRANCH}" in _remote_branches(landed_lane.repo)


def test_dirty_worktree_is_preserved_with_the_reason_named(landed_lane):
    """Uncommitted work outranks a landed merge."""
    _land_on_main(landed_lane.repo)
    (landed_lane.worktree / "scratch.txt").write_text("wip\n", encoding="utf-8")

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        run_git=_run_git, emit=lambda *_a, **_kw: None,
    )

    assert len(preserved) == 1
    assert "dirty or unverifiable" in preserved[0]
    assert "scratch.txt" in preserved[0]
    assert landed_lane.worktree.exists()


def test_nested_ignore_rules_make_residue_disposable(landed_lane):
    """A repository-owned nested ignore rule authorizes forced removal."""
    _land_on_main(landed_lane.repo)
    generated = landed_lane.worktree / "webapp" / "generated" / "bundle.js"
    generated.parent.mkdir()
    generated.write_text("built\n", encoding="utf-8")

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo),
        branch=BRANCH,
        target="main",
        run_git=_run_git,
        emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert not landed_lane.worktree.exists()


def test_landed_lane_records_the_row_release(landed_lane, monkeypatch):
    """The row describes the directory, so it retires with it."""
    _land_on_main(landed_lane.repo)
    calls: list[tuple] = []

    def dispatch(*, function_id, target, payload):
        calls.append((function_id, target.item_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        dispatch,
    )

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        item_id=7, run_git=_run_git, emit=lambda *_a, **_kw: None,
    )

    assert preserved == ()
    assert calls == [
        ("item_worktrees.release_merged_lane", 7, {"branch": BRANCH}),
    ]


def test_row_release_failure_warns_without_unwinding_the_merge(monkeypatch):
    """The merge already landed; a refused row release cannot undo it."""
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=False, result=None,
            error=SimpleNamespace(message="control plane down"),
        ),
    )
    said: list[str] = []

    warning = release_lane_row(
        7, BRANCH, emit=lambda message, **_kw: said.append(message),
    )

    assert warning is not None
    assert "left active after worktree removal" in warning
    assert warning in said
    assert "control plane down" in warning


def test_claim_required_release_is_not_a_left_active_warning(monkeypatch):
    """The terminal transition already released the row and the claim."""
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=False, result=None,
            error=SimpleNamespace(
                message=(
                    "no active claim by session 's' on item YOK-1; "
                    "acquire one first: yoke claims work acquire"
                ),
            ),
        ),
    )
    said: list[str] = []

    warning = release_lane_row(
        7, BRANCH, emit=lambda message, **_kw: said.append(message),
    )

    assert warning is None
    assert said == []


def test_row_release_warning_is_returned_from_prune(landed_lane, monkeypatch):
    """The merge envelope carries any warning that was actually emitted."""
    _land_on_main(landed_lane.repo)
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **_kw: SimpleNamespace(
            success=False, result=None,
            error=SimpleNamespace(message="control plane down"),
        ),
    )

    preserved = prune_landed_lane(
        repo_root=str(landed_lane.repo), branch=BRANCH, target="main",
        item_id=7, run_git=_run_git, emit=lambda *_a, **_kw: None,
    )

    assert any("left active after worktree removal" in note for note in preserved)
    assert any("control plane down" in note for note in preserved)

"""A lane holding copies of merged commits closes out on the merge it has.

Built on real history rather than stubs, because the whole defect lives in
what Git will and will not say: the duplicate commits are byte-identical
patches under fresh shas, and only a patch-identity read connects them to the
merge that already took them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_landed as landed

BRANCH = "ITEM-1"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _landed_lane_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A merged lane, later commits on main, and the lane rewound to copies.

    Returns ``(repo, base_before_the_lane, landed_lane_head, merge_commit)``.
    The lane ends up where a close-out re-entry finds it after a rebase that
    kept its commits: pointing at a patch-identical copy of work the base
    branch merged, on a base that predates everything merged since.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    base = _commit(repo, "README.md", "start\n")

    _git(repo, "checkout", "-b", BRANCH)
    lane_head = _commit(repo, "feature.py", "feature\n")

    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", BRANCH, "-m", f"Merge pull request #1 from {BRANCH}")
    merge_commit = _git(repo, "rev-parse", "HEAD")

    # What close-out must not revert: work merged after this lane landed.
    _commit(repo, "later_one.py", "one\n")
    _commit(repo, "later_two.py", "two\n")

    # The lane as a re-entry finds it: the same patch, a new sha, an old base.
    _git(repo, "checkout", "-B", BRANCH, base)
    _git(repo, "cherry-pick", lane_head)
    _git(repo, "checkout", "main")
    return repo, base, lane_head, merge_commit


def _receipt(lane_head: str, merge_commit: str) -> receipts.MergeReceipt:
    return receipts.MergeReceipt(
        branch=BRANCH,
        target="main",
        commit_sha=lane_head,
        merge_sha=merge_commit,
        touched_files=("feature.py",),
    )


def _look(repo: Path) -> dict:
    return dict(item_id=7, branch=BRANCH, target="main", repo_root=str(repo))


def test_a_copied_commit_is_unlanded_by_sha_and_landed_by_patch(tmp_path):
    repo, _base, _lane_head, _merge = _landed_lane_repo(tmp_path)
    copy = _git(repo, "rev-parse", BRANCH)

    assert git.is_ancestor(str(repo), copy, "main") is False
    assert git.unlanded_patches(str(repo), copy, "main") == ()


def test_a_copied_lane_closes_out_on_the_merge_identity_it_already_has(
    tmp_path,
    monkeypatch,
):
    repo, _base, lane_head, merge_commit = _landed_lane_repo(tmp_path)
    monkeypatch.setattr(
        landed.receipts,
        "load",
        lambda *_a, **_k: _receipt(lane_head, merge_commit),
    )

    lane = landed.landed_lane(**_look(repo), project="yoke")

    assert lane is not None
    assert lane.source == "rebased copy of the landed lane"
    assert (lane.commit_sha, lane.merge_sha) == (lane_head, merge_commit)
    assert lane.commit_sha != _git(repo, "rev-parse", BRANCH)
    assert landed.stale_unlanded_work(**_look(repo)) == ""


def test_the_copied_lane_is_the_one_whose_diff_would_revert_later_merges(
    tmp_path,
    monkeypatch,
):
    """The convergence is what keeps that diff from being published at all."""
    repo, _base, lane_head, merge_commit = _landed_lane_repo(tmp_path)
    copy = _git(repo, "rev-parse", BRANCH)
    reverted = _git(repo, "diff", "--name-only", "main", copy).split()
    assert sorted(reverted) == ["later_one.py", "later_two.py"]

    monkeypatch.setattr(
        landed.receipts,
        "load",
        lambda *_a, **_k: _receipt(lane_head, merge_commit),
    )
    lane = landed.landed_lane(**_look(repo), project="yoke")

    assert lane is not None and lane.touched_files == ("feature.py",)


def test_a_lane_with_a_commit_of_its_own_still_has_work_to_land(
    tmp_path,
    monkeypatch,
):
    repo, _base, lane_head, merge_commit = _landed_lane_repo(tmp_path)
    _git(repo, "checkout", BRANCH)
    _commit(repo, "retry.py", "retry\n")
    _git(repo, "checkout", "main")
    monkeypatch.setattr(
        landed.receipts,
        "load",
        lambda *_a, **_k: _receipt(lane_head, merge_commit),
    )

    assert git.unlanded_patches(str(repo), _git(repo, "rev-parse", BRANCH), "main")
    assert landed.landed_lane(**_look(repo), project="yoke") is None
    assert "fresh work item" in landed.stale_unlanded_work(**_look(repo))


def test_a_receipt_the_base_does_not_contain_converges_nothing(
    tmp_path,
    monkeypatch,
):
    """Patch equivalence alone is not a landing; a recorded merge must be one.

    The receipt here names the copy rather than the commit the merge took, so
    nothing recorded is on the base branch and there is no identity to
    converge on — whatever the patches say.
    """
    repo, _base, _lane_head, _merge = _landed_lane_repo(tmp_path)
    copy = _git(repo, "rev-parse", BRANCH)
    monkeypatch.setattr(
        landed.receipts,
        "load",
        lambda *_a, **_k: _receipt(copy, ""),
    )

    assert git.unlanded_patches(str(repo), copy, "main") == ()
    assert landed.landed_lane(**_look(repo), project="yoke") is None


def test_an_unreadable_comparison_is_not_a_landing(tmp_path, monkeypatch):
    repo, _base, lane_head, merge_commit = _landed_lane_repo(tmp_path)
    receipt = _receipt(lane_head, merge_commit)
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: receipt)
    monkeypatch.setattr(landed.git, "unlanded_patches", lambda *_a: None)

    assert landed.landed_lane(**_look(repo), project="yoke") is None

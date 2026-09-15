"""Merge A, a release-stage QA failure sends it back for rework, merge B.

The joined proof this session's pieces individually cover: an item's own
next legitimate merge attempt after genuinely returning short of release is
not refused as foreign/stale work (``stale_unlanded_work``'s
``reached_release`` parameter), while A's own git history and receipt
identity are never silently reused for B once the item has moved on.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_landed as landed

BRANCH = "ITEM-1"
TARGET = "main"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", TARGET)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", BRANCH)
    return root


class _FakeReceiptStore:
    """The real contract: one entry per (branch, target), overwritten by the
    latest merge's own facts -- current state, not a history of merges."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], receipts.MergeReceipt] = {}

    def load(self, _item_id: int, branch: str, target: str):
        return self._entries.get((branch, target))

    def record(self, _item_id: int, receipt: receipts.MergeReceipt) -> str:
        self._entries[(receipt.branch, receipt.target)] = receipt
        return ""


def _lane(item_id: int, repo_root: Path) -> landed.LandedLane | None:
    return landed.landed_lane(
        item_id=item_id, branch=BRANCH, target=TARGET,
        repo_root=str(repo_root), project="yoke",
    )


def test_merge_a_then_rework_then_merge_b_preserves_a_and_admits_b(
    repo: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeReceiptStore()
    monkeypatch.setattr(landed.receipts, "load", store.load)
    monkeypatch.setattr(landed.receipts, "record", store.record)

    # --- Merge A lands: reviewing-implementation -> release ---
    a_commit = _git(repo, "rev-parse", BRANCH)
    _git(repo, "checkout", "-q", TARGET)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge A", BRANCH)
    a_merge_sha = _git(repo, "rev-parse", TARGET)
    receipts.record(
        7,
        receipts.MergeReceipt(
            branch=BRANCH, target=TARGET, commit_sha=a_commit,
            merge_sha=a_merge_sha, touched_files=("feature.py",),
        ),
    )

    lane_a = _lane(7, repo)
    assert lane_a is not None
    assert lane_a.commit_sha == a_commit
    assert lane_a.merge_sha == a_merge_sha
    # Still at "release": this same lane is the landing, not stale work.
    assert landed.stale_unlanded_work(
        item_id=7, branch=BRANCH, target=TARGET, repo_root=str(repo),
        recorded_head="", reached_release=True,
    ) == ""

    # --- A failed release-stage QA: the item returns to implementing for a
    # fix, exactly the generic backward-transition-is-rework path this
    # session verified against every pinned workflow's declared edges.
    # The rework adds a new commit to the SAME branch (unlanded again).
    _git(repo, "checkout", "-q", BRANCH)
    (repo / "feature.py").write_text("fixed\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-q", "-m", "rework after failed release QA")
    b_commit = _git(repo, "rev-parse", BRANCH)

    # A fresh merge attempt on this same lane, now genuinely short of
    # release again, must not be refused as foreign/stale work.
    assert landed.stale_unlanded_work(
        item_id=7, branch=BRANCH, target=TARGET, repo_root=str(repo),
        recorded_head="", reached_release=False,
    ) == ""
    # The stale receipt no longer answers for the branch's new head.
    assert _lane(7, repo) is None

    # --- Merge B lands ---
    _git(repo, "checkout", "-q", TARGET)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge B", BRANCH)
    b_merge_sha = _git(repo, "rev-parse", TARGET)
    receipts.record(
        7,
        receipts.MergeReceipt(
            branch=BRANCH, target=TARGET, commit_sha=b_commit,
            merge_sha=b_merge_sha, touched_files=("feature.py",),
        ),
    )

    # The receipt now answers for B -- current state, not a history of merges.
    lane_b = _lane(7, repo)
    assert lane_b is not None
    assert lane_b.commit_sha == b_commit
    assert lane_b.merge_sha == b_merge_sha
    assert lane_b.merge_sha != a_merge_sha

    # A's own history is not lost: its commit is still a real ancestor of
    # the target, independent of what the current receipt now names.
    assert _git(repo, "merge-base", "--is-ancestor", a_commit, TARGET) == ""
    assert _git(repo, "merge-base", "--is-ancestor", a_merge_sha, TARGET) == ""

    # A late callback bound to A's own superseded merge identity must not
    # be read as answering for the item's current (B) landing.
    current = receipts.load(7, BRANCH, TARGET)
    assert current is not None
    assert current.merge_sha == b_merge_sha
    assert current.merge_sha != a_merge_sha

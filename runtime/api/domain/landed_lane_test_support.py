"""Shared fakes for the reads that decide whether a lane already landed.

Every answer a lane lookup takes from the checkout is served here, so no
test of that decision reaches a real repository, and two test modules ask
the same questions the same way.
"""

from __future__ import annotations

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_stale_lane as stale_lane

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
RECEIPT = receipts.MergeReceipt(
    branch="ITEM-1",
    target="main",
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("feature.py",),
)
LOOK = dict(item_id=7, branch="ITEM-1", target="main", repo_root="/repo")


def probe(
    monkeypatch,
    *,
    branch_exists: bool,
    head: str,
    contains: tuple[str, ...],
    unlanded: tuple[str, ...] | None = ("9" * 40,),
    adds_nothing: bool | None = None,
):
    """Answer every read of the checkout, so no test reaches a real repo.

    ``unlanded`` is the patch-identity answer: a lane still carrying a commit
    of its own by default, which is what keeps these cases about shas.
    ``adds_nothing`` is the tree answer, unreadable by default for the same
    reason.
    """
    monkeypatch.setattr(landed.git, "lane_adds_nothing", lambda *_a: adds_nothing)
    # The refusal reads its own module-level git and receipts, so the probe
    # answers for both modules or the two disagree about one lane.
    monkeypatch.setattr(stale_lane, "git", landed.git)
    monkeypatch.setattr(stale_lane, "receipts", landed.receipts)
    monkeypatch.setattr(landed.git, "branch_exists", lambda *_a: branch_exists)
    monkeypatch.setattr(landed.git, "head_of", lambda *_a: head)
    monkeypatch.setattr(landed.git, "current_base_ref", lambda _repo, target: target)
    monkeypatch.setattr(landed.git, "unlanded_commits", lambda *_a: unlanded)
    monkeypatch.setattr(
        landed.git,
        "containing_ref",
        lambda _repo, commit, target: target if commit in contains else "",
    )
    monkeypatch.setattr(
        landed.git,
        "is_ancestor",
        lambda _repo, commit, _ref: commit in contains,
    )


def _lane(**kw):
    return landed.landed_lane(**LOOK, project="yoke", **kw)


def lane(**kw):
    """The landing this lane already has, under the probe's answers."""
    return landed.landed_lane(**LOOK, project="yoke", **kw)

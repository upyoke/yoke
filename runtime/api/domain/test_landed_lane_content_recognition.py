"""Extra lane commits that reached the base under a companion item's landing.

Those commits are foreign shas to the base and no receipt of this item's names
them, so every sha read calls them new work and close-out heads off to open a
second pull request for content that is already delivered. The tree answer is
the one that sees it.

It decides only whether the lane carries anything BEYOND a landing that
already happened — a recorded merge on the base is still required first, and
still required to be what the convergence records.
"""

from __future__ import annotations

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_landed as landed


_LOOK = dict(item_id=7, branch="ITEM-1", target="main", repo_root="/repo")
MERGE_SHA = "2" * 40
LANE_HEAD = "3" * 40


def _probe(
    monkeypatch,
    *,
    contains: tuple[str, ...],
    adds_nothing: bool | None,
    recorded: str | None = MERGE_SHA,
):
    """Answer every read of the checkout, so no test reaches a real repo.

    ``unlanded_commits`` always reports a commit of the lane's own, so these
    cases turn entirely on the tree answer rather than on patch identity.
    ``recorded`` is the landing the receipt names; ``None`` means no receipt.
    """
    monkeypatch.setattr(landed.git, "lane_adds_nothing", lambda *_a: adds_nothing)
    monkeypatch.setattr(landed.git, "branch_exists", lambda *_a: True)
    monkeypatch.setattr(landed.git, "head_of", lambda *_a: LANE_HEAD)
    monkeypatch.setattr(landed.git, "current_base_ref", lambda _repo, target: target)
    monkeypatch.setattr(landed.git, "unlanded_commits", lambda *_a: ("9" * 40,))
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
    receipt = (
        None
        if recorded is None
        else receipts.MergeReceipt(
            branch="ITEM-1",
            target="main",
            commit_sha=recorded,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
        )
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: receipt)


def _lane():
    return landed.landed_lane(**_LOOK, project="yoke")


def test_a_lane_that_adds_nothing_beyond_its_landing_is_a_landing(monkeypatch):
    _probe(monkeypatch, contains=(MERGE_SHA,), adds_nothing=True)
    lane = _lane()
    assert lane is not None
    assert lane.source == "rebased copy of the landed lane"


def test_content_equivalence_alone_is_still_not_a_landing(monkeypatch):
    """A recorded merge must be on the base, whatever the content says.

    The tree read decides whether the lane carries anything beyond a landing
    that already happened. It never supplies the landing: with no recorded
    merge on the base there is no identity to converge on, and converging
    anyway would close an item out against a merge nobody made.
    """
    _probe(monkeypatch, contains=(), adds_nothing=True, recorded=None)
    assert landed.replayed_base_ref("/repo", LANE_HEAD, "main", None) == ""
    assert _lane() is None


def test_a_landing_the_base_does_not_contain_is_not_one(monkeypatch):
    """Recorded is not enough; the base has to actually hold it."""
    _probe(monkeypatch, contains=(), adds_nothing=True)
    assert _lane() is None


def test_a_lane_still_carrying_content_is_not_a_landing(monkeypatch):
    _probe(monkeypatch, contains=(MERGE_SHA,), adds_nothing=False)
    assert _lane() is None


def test_an_unreadable_tree_comparison_decides_nothing(monkeypatch):
    """Unreadable must never read as "already landed"."""
    _probe(monkeypatch, contains=(MERGE_SHA,), adds_nothing=None)
    assert _lane() is None

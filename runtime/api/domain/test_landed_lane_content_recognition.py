"""A lane whose work reached the base under a companion item's landing.

The shas are foreign to the base and no receipt of this item's names them, so
every sha read says "new work" and close-out heads off to open a second pull
request for content that is already delivered. The tree answer is the one
that sees it — and the one that must still refuse when the lane really does
carry something.
"""

from __future__ import annotations

from yoke_core.domain import standalone_item_merge_landed as landed


_LOOK = dict(item_id=7, branch="ITEM-1", target="main", repo_root="/repo")
MERGE_SHA = "2" * 40
LANE_HEAD = "3" * 40


def _probe(
    monkeypatch,
    *,
    contains: tuple[str, ...],
    adds_nothing: bool | None,
):
    """Answer every read of the checkout, so no test reaches a real repo.

    ``unlanded_commits`` always reports a commit of the lane's own, so these
    cases turn entirely on the tree answer rather than on patch identity.
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


def _lane():
    return landed.landed_lane(**_LOOK, project="yoke")


def test_a_lane_that_adds_nothing_is_a_landing(monkeypatch):
    _probe(monkeypatch, contains=(MERGE_SHA,), adds_nothing=True)
    lane = _lane()
    assert lane is not None
    assert lane.source == "rebased copy of the landed lane"


def test_it_needs_no_receipt_of_its_own(monkeypatch):
    """The companion item's landing is the one that happened."""
    _probe(monkeypatch, contains=(), adds_nothing=True)
    assert landed._replayed_base_ref("/repo", LANE_HEAD, "main", None) == "main"


def test_a_lane_still_carrying_content_is_not_a_landing(monkeypatch):
    _probe(monkeypatch, contains=(), adds_nothing=False)
    assert _lane() is None


def test_an_unreadable_tree_comparison_decides_nothing(monkeypatch):
    """Unreadable must never read as "already landed"."""
    _probe(monkeypatch, contains=(), adds_nothing=None)
    assert _lane() is None

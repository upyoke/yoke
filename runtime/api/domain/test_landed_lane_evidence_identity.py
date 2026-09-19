"""What a landed lane's evidence record is answerable for.

A lane that lands twice has both candidates on the base, each carried by a
merge of its own. The identity close-out records — the commit, the merge,
and the file set — has to describe the landing it is closing out, not the
one it replaced.
"""

from __future__ import annotations

from yoke_core.domain import standalone_item_merge_landed as landed
from runtime.api.domain.landed_lane_test_support import (
    LANE_SHA,
    MERGE_SHA,
    RECEIPT,
    lane as _lane,
    probe as _probe,
)


RELANDED_SHA = "7" * 40
RELANDED_MERGE = "8" * 40


def _two_landings(monkeypatch):
    """A lane on the base twice: the receipt's landing, then this one."""
    _probe(
        monkeypatch,
        branch_exists=True,
        head=RELANDED_SHA,
        contains=(RELANDED_SHA, LANE_SHA, MERGE_SHA, RELANDED_MERGE),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    monkeypatch.setattr(
        landed.receipts,
        "landing_merge_commit",
        lambda _root, _target, commit_sha: (
            RELANDED_MERGE if commit_sha == RELANDED_SHA else MERGE_SHA
        ),
    )


def test_a_relanded_lane_describes_the_landing_that_carried_it(monkeypatch):
    """Evidence must not name the landing this close-out replaced.

    The superseded candidate is equally on the base and equally carried by
    a merge, so preferring the recorded receipt dated the item from that
    older merge and reported its file set as this landing's.
    """
    _two_landings(monkeypatch)
    monkeypatch.setattr(
        landed.receipts,
        "touched_files_from_merge_commit",
        lambda _root, _target, commit_sha: (
            ("relanded.py",) if commit_sha == RELANDED_SHA else ("feature.py",)
        ),
    )
    lane = _lane()
    assert lane is not None
    assert lane.candidate_sha == RELANDED_SHA
    assert lane.commit_sha == RELANDED_SHA
    assert lane.merge_sha == RELANDED_MERGE
    assert lane.touched_files == ("relanded.py",)


def test_a_receipt_for_this_same_landing_still_names_the_work(monkeypatch):
    """The receipt's whole point: a lane pointing at its own merge commit."""
    _probe(
        monkeypatch,
        branch_exists=True,
        head=MERGE_SHA,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    # A fast-forwarded lane head names no landing merge of its own, which
    # is exactly when the receipt is the only identity there is.
    monkeypatch.setattr(
        landed.receipts, "landing_merge_commit", lambda *_a: ""
    )
    monkeypatch.setattr(
        landed.receipts, "resolve_touched_files", lambda **_k: ("feature.py",)
    )
    lane = _lane()
    assert lane is not None
    assert lane.commit_sha == LANE_SHA
    assert lane.candidate_sha == MERGE_SHA
    assert lane.merge_sha == MERGE_SHA

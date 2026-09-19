"""A recorded candidate answers for its own lane, whatever the branch did.

``landed_lane`` is asked about a lane whose local branch may be gone, stale,
or standing on an earlier landing of the same name. These cases pin which
commit it answers for, because getting that wrong records a merge that
predates the work and advances an item on a candidate nothing landed.
"""

from __future__ import annotations

from runtime.api.domain.test_standalone_item_merge_landed import (  # noqa: F401
    LANE_SHA,
    MERGE_SHA,
    RECEIPT,
    _lane,
    _probe,
)
from yoke_core.domain import standalone_item_merge_landed as landed


NEW_CANDIDATE = "3" * 40


def test_a_recorded_candidate_the_base_lacks_is_not_a_landing(monkeypatch):
    """An earlier landing on the same branch name is not this candidate's.

    A branch name outlives the landing it had. When the item is reopened and
    a new candidate is authored, verified and published, a stale local ref
    still sitting on the earlier merge used to satisfy the recorded
    identities — and close-out reported already_merged against a merge SHA
    that predates the work, then advanced the item on a candidate nothing
    had landed.
    """
    _probe(
        monkeypatch,
        branch_exists=True,
        head=LANE_SHA,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    assert _lane(recorded_head=NEW_CANDIDATE) is None


def test_a_recorded_candidate_the_base_holds_by_content_still_converges(
    monkeypatch,
):
    _probe(
        monkeypatch,
        branch_exists=False,
        head="",
        contains=(LANE_SHA, MERGE_SHA),
        adds_nothing=True,
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    lane = _lane(recorded_head=NEW_CANDIDATE)

    assert lane is not None
    assert lane.source == "rebased copy of the landed lane"


def test_a_gone_branch_with_an_unlanded_candidate_re_merges(monkeypatch):
    """The receipt's own shas never answer for a candidate that exists."""
    _probe(
        monkeypatch,
        branch_exists=False,
        head="",
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    assert _lane(recorded_head=NEW_CANDIDATE) is None

"""A queue landing's merged_at dates the merge, not the close-out.

The queue close-out used to stamp merged_at as its first statement, before
it had resolved which merge it was answering for. That records when
close-out reached the line: hours after the merge for a re-entered
close-out, and for an item landing a second time a date belonging to the
landing it just replaced. So the stamp waits until the merge commit is
known and carries it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.engines.merge_worktree_pr_train_run import TrainRunLookupFailure
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
COMBINED_SHA = "h" * 40
MERGE_SHA = "m" * 40
REPO_ROOT = "/repo"


def _ctx(repo_root: str = REPO_ROOT) -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"),
        repo_root=repo_root,
        project="yoke",
    )


def _wire(monkeypatch, *, batch: Any, failure: Any = None) -> dict:
    stamped: dict = {}

    def stamp(item_id, **kwargs):
        stamped.update(item_id=item_id, **kwargs)
        return None

    monkeypatch.setattr(close_out_mod, "stamp_merged_at", stamp)
    monkeypatch.setattr(
        close_out_mod, "read_recorded_batch", lambda item_id, *, pr_num: None
    )
    monkeypatch.setattr(
        close_out_mod,
        "observe_batch",
        lambda ctx, *, pr_num, member_snapshot, drift_check=None,
        landed_merge_sha="": (batch, failure),
    )
    monkeypatch.setattr(
        close_out_mod, "record_batch_evidence", lambda item_id, receipt, **_kw: None
    )
    monkeypatch.setattr(
        close_out_mod,
        "read_pr_changed_files",
        lambda ctx, pr_num: (("runtime/api/thing.py",), None),
    )
    monkeypatch.setattr(close_out_mod.receipts, "record", lambda *_a, **_kw: "")
    monkeypatch.setattr(close_out_mod, "fast_forward_main_checkout", lambda *_a: "")
    return stamped


def test_the_stamp_names_the_merge_this_landing_resolved(monkeypatch) -> None:
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        members=("YOK-200",),
        head_sha=COMBINED_SHA,
        run_url="https://runs/42",
    )
    stamped = _wire(monkeypatch, batch=batch)

    close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert stamped == {
        "item_id": 7,
        "repo_root": REPO_ROOT,
        "merge_sha": MERGE_SHA,
    }


def test_an_unresolved_merge_stamps_without_one_rather_than_a_wrong_sha(
    monkeypatch,
) -> None:
    """No resolved merge leaves the stamp its fallback, and it keeps coalescing."""
    stamped = _wire(
        monkeypatch,
        batch=None,
        failure=TrainRunLookupFailure(
            reason="merge-group run not found", recovery="", retryable=True
        ),
    )

    close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert stamped == {"item_id": 7, "repo_root": REPO_ROOT, "merge_sha": ""}


def test_a_checkout_less_context_still_stamps(monkeypatch) -> None:
    """An empty repo_root is a fallback, never a crash mid-close-out."""
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        members=("YOK-200",),
        head_sha=COMBINED_SHA,
        run_url="https://runs/42",
    )
    stamped = _wire(monkeypatch, batch=batch)

    close_out_mod.record_landing(
        _ctx(""), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert stamped == {"item_id": 7, "repo_root": "", "merge_sha": MERGE_SHA}

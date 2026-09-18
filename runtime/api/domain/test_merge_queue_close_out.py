"""A landed queue member must record what its merge is answerable for."""

from __future__ import annotations

import pytest

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.item_merge_receipts import MergeReceipt
from yoke_core.engines.merge_worktree_pr_train_run import TrainRunLookupFailure
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
COMBINED_SHA = "h" * 40
MERGE_SHA = "m" * 40
RUN_URL = "https://runs/42"


def _ctx(repo_root: str = "") -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"),
        repo_root=repo_root,
        project="yoke",
    )


def _wire(
    monkeypatch,
    *,
    batch=None,
    batch_warning=None,
    batch_recovery="",
    batch_retryable=True,
    recorded_batch=None,
    touched=("runtime/api/thing.py",),
    files_error=None,
):
    recorded: dict = {}
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda item_id: None)
    # No receipt recorded yet, so every case here exercises the derivation.
    monkeypatch.setattr(
        close_out_mod, "read_recorded_batch",
        lambda item_id, *, pr_num: recorded_batch,
    )
    failure = (
        None
        if batch_warning is None
        else TrainRunLookupFailure(
            reason=batch_warning,
            recovery=batch_recovery,
            retryable=batch_retryable,
        )
    )
    monkeypatch.setattr(
        close_out_mod, "observe_batch",
        lambda ctx, *, pr_num, member_snapshot, drift_check=None: (
            batch,
            failure,
        ),
    )
    monkeypatch.setattr(
        close_out_mod, "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )
    monkeypatch.setattr(
        close_out_mod, "read_pr_changed_files",
        lambda ctx, pr_num: (touched, files_error),
    )

    def record(item_id, receipt: MergeReceipt) -> str:
        recorded.update(item_id=item_id, receipt=receipt)
        return ""

    monkeypatch.setattr(close_out_mod.receipts, "record", record)
    monkeypatch.setattr(
        close_out_mod, "fast_forward_main_checkout", lambda *_a: ""
    )
    return recorded


def test_landing_records_the_merge_receipt_the_terminal_gate_reads(monkeypatch):
    """The queue merge happens on GitHub, so nothing local records it.

    Without this receipt the terminal QA gate has no landing identity to
    compare blocking runs against and every queue-landed item strands.
    """
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, members=("YOK-200",),
        head_sha=COMBINED_SHA, run_url=RUN_URL,
    )
    recorded = _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.merge_sha == MERGE_SHA
    assert outcome.batch == batch
    assert outcome.ci_evidence_error == ""
    assert outcome.warnings == ()
    assert recorded["item_id"] == 7
    assert recorded["receipt"] == MergeReceipt(
        branch="YOK-200", target="main",
        commit_sha=LANE_SHA, merge_sha=MERGE_SHA,
        touched_files=("runtime/api/thing.py",),
    )


def test_landing_carries_the_file_set_the_evidence_record_needs(monkeypatch):
    """Nothing local can diff a queue landing, so the pull request answers.

    The item's execution evidence is refused without touched files, so a
    landing that resolves none lands the merge and then strands the item.
    """
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    recorded = _wire(
        monkeypatch, batch=batch, touched=("a.py", "docs/b.md"),
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.touched_files == ("a.py", "docs/b.md")
    assert outcome.warnings == ()
    assert recorded["receipt"].touched_files == ("a.py", "docs/b.md")


def test_unresolvable_file_set_warns_without_unwinding_the_landing(monkeypatch):
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(
        monkeypatch, batch=batch, touched=None,
        files_error="github pr read failure: 503",
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.merge_sha == MERGE_SHA
    assert outcome.touched_files == ()
    assert (
        "touched files not resolved: github pr read failure: 503"
        in outcome.warnings
    )


def test_empty_file_listing_is_reported_rather_than_recorded_silently(
    monkeypatch,
):
    """A merged pull request that changed nothing is a fact worth naming."""
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch, touched=())

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.touched_files == ()
    assert "pull request 42 reports no changed files" in outcome.warnings


def test_unresolved_batch_still_records_the_lane_head(monkeypatch):
    """An unreadable train is a warning, not a lost landing identity."""
    recorded = _wire(
        monkeypatch, batch=None, batch_warning="merge_group run lookup failed",
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.merge_sha == ""
    assert outcome.ci_evidence_error == "merge_group run lookup failed"
    assert "merge_group run lookup failed" in outcome.warnings
    assert recorded["receipt"].commit_sha == LANE_SHA


def test_unidentified_train_cannot_be_recorded_as_passing_ci(monkeypatch):
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA)
    _wire(monkeypatch, batch=batch, batch_warning="train run not identified")
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda *_a, **_k: pytest.fail("an unidentified run is not passing proof"),
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.ci_evidence_error == "train run not identified"


def test_landing_leaves_lane_retirement_to_terminal_close_out(monkeypatch):
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx("/repo"), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.warnings == ()
    assert outcome.merge_sha == MERGE_SHA


def test_a_landing_with_no_local_checkout_prunes_nothing(monkeypatch):
    """A caller holding no repository has no lane on disk to retire."""
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.warnings == ()


def test_landing_fast_forwards_main_without_removing_the_lane(monkeypatch):
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    order: list[str] = []
    monkeypatch.setattr(
        close_out_mod, "fast_forward_main_checkout",
        lambda root, target: order.append(f"sync:{root}:{target}") or "",
    )

    outcome = close_out_mod.record_landing(
        _ctx("/tmp/repo"), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.warnings == ()
    assert order == ["sync:/tmp/repo:main"]


def test_ci_recording_failure_keeps_close_out_retriable(monkeypatch):
    """The merge stays landed, but terminal evidence must wait for CI proof."""
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    monkeypatch.setattr(
        close_out_mod, "stamp_merged_at", lambda item_id: "control plane down",
    )
    monkeypatch.setattr(
        close_out_mod, "record_batch_evidence",
        lambda item_id, receipt, **_kw: "evidence write refused",
    )
    monkeypatch.setattr(
        close_out_mod.receipts, "record",
        lambda item_id, receipt, **_kw: "merge receipt not recorded: down",
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert "merged_at not recorded: control plane down" in outcome.warnings
    assert "batch evidence not recorded: evidence write refused" in outcome.warnings
    assert "merge receipt not recorded: down" in outcome.warnings
    assert outcome.ci_evidence_error == "evidence write refused"
    assert "Re-run yoke merge item YOK-200" in outcome.ci_evidence_refusal(
        "42", "yoke merge item YOK-200"
    )


def test_a_recorded_receipt_is_reused_rather_than_re_derived(monkeypatch):
    """The second close-out reads what the first one wrote.

    A member that parks at a release wait reaches this again hours later,
    long after GitHub's merge_group runs collection is the easy answer. The
    receipt its own landing recorded does not decay, so re-deriving it can
    only agree or fail — and failing is what stranded members whose proof was
    sitting in their own QA rows.
    """
    stored = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, recorded_batch=stored)
    monkeypatch.setattr(
        close_out_mod,
        "observe_batch",
        lambda *_a, **_k: pytest.fail("a recorded receipt must not be re-derived"),
    )
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda *_a, **_k: pytest.fail("a recorded receipt must not be re-recorded"),
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.ci_evidence_error == ""
    assert outcome.merge_sha == MERGE_SHA
    assert outcome.batch is stored


def test_a_search_that_cannot_succeed_does_not_prescribe_a_re_run(monkeypatch):
    """Naming a retry for a stable answer is a loop with no exit."""
    _wire(
        monkeypatch,
        batch=None,
        batch_warning="no merge_group workflow run identified for pull request 42",
        batch_recovery="Confirm the queue ran that workflow on the merge group.",
        batch_retryable=False,
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )
    refusal = outcome.ci_evidence_refusal("42", "yoke merge item YOK-200")

    assert "Re-run" not in refusal
    assert "reaches the same answer" in refusal
    assert "Confirm the queue ran that workflow" in refusal

"""A landed queue member must record what its merge is answerable for."""

from __future__ import annotations

from runtime.api.domain.merge_queue_close_out_test_support import (
    COMBINED_SHA as COMBINED_SHA,
    LANE_SHA as LANE_SHA,
    MERGE_SHA as MERGE_SHA,
    RUN_URL as RUN_URL,
    _ctx as _ctx,
    _wire as _wire,
)


import pytest

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.item_merge_receipts import MergeReceipt


def test_landing_records_the_merge_receipt_the_terminal_gate_reads(monkeypatch):
    """The queue merge happens on GitHub, so nothing local records it.

    Without this receipt the terminal QA gate has no landing identity to
    compare blocking runs against and every queue-landed item strands.
    """
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        members=("YOK-200",),
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    recorded = _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.merge_sha == MERGE_SHA
    assert outcome.batch == batch
    assert outcome.ci_evidence_error == ""
    assert outcome.warnings == ()
    assert recorded["item_id"] == 7
    assert recorded["receipt"] == MergeReceipt(
        branch="YOK-200",
        target="main",
        commit_sha=LANE_SHA,
        merge_sha=MERGE_SHA,
        touched_files=("runtime/api/thing.py",),
    )


def test_landing_carries_the_file_set_the_evidence_record_needs(monkeypatch):
    """Nothing local can diff a queue landing, so the pull request answers.

    The item's execution evidence is refused without touched files, so a
    landing that resolves none lands the merge and then strands the item.
    """
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    recorded = _wire(
        monkeypatch,
        batch=batch,
        touched=("a.py", "docs/b.md"),
    )

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.touched_files == ("a.py", "docs/b.md")
    assert outcome.warnings == ()
    assert recorded["receipt"].touched_files == ("a.py", "docs/b.md")


def test_unresolvable_file_set_warns_without_unwinding_the_landing(monkeypatch):
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(
        monkeypatch,
        batch=batch,
        touched=None,
        files_error="github pr read failure: 503",
    )

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.merge_sha == MERGE_SHA
    assert outcome.touched_files == ()
    assert "touched files not resolved: github pr read failure: 503" in outcome.warnings


def test_empty_file_listing_is_reported_rather_than_recorded_silently(
    monkeypatch,
):
    """A merged pull request that changed nothing is a fact worth naming."""
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch, touched=())

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.touched_files == ()
    assert "pull request 42 reports no changed files" in outcome.warnings


def test_unresolved_batch_still_records_the_lane_head(monkeypatch):
    """An unreadable train is a warning, not a lost landing identity."""
    recorded = _wire(
        monkeypatch,
        batch=None,
        batch_warning="merge_group run lookup failed",
        landing_merge="",
    )

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.merge_sha == LANE_SHA
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
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.ci_evidence_error == "train run not identified"


def test_landing_leaves_lane_retirement_to_terminal_close_out(monkeypatch):
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx("/repo"),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.warnings == ()
    assert outcome.merge_sha == MERGE_SHA


def test_a_landing_with_no_local_checkout_prunes_nothing(monkeypatch):
    """A caller holding no repository has no lane on disk to retire."""
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.warnings == ()


def test_landing_fast_forwards_main_without_removing_the_lane(monkeypatch):
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    order: list[str] = []
    monkeypatch.setattr(
        close_out_mod,
        "fast_forward_main_checkout",
        lambda root, target: order.append(f"sync:{root}:{target}") or "",
    )

    outcome = close_out_mod.record_landing(
        _ctx("/tmp/repo"),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )

    assert outcome.warnings == ()
    assert order == ["sync:/tmp/repo:main"]

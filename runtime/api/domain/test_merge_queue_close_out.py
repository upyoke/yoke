"""A landed queue member must record what its merge is answerable for."""

from __future__ import annotations

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.standalone_item_merge_receipt import MergeReceipt
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
COMBINED_SHA = "h" * 40
MERGE_SHA = "m" * 40


def _ctx() -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"), project="yoke"
    )


def _wire(monkeypatch, *, batch=None, batch_warning=None):
    recorded: dict = {}
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda item_id: None)
    monkeypatch.setattr(
        close_out_mod, "observe_batch",
        lambda ctx, *, pr_num, member_snapshot: (batch, batch_warning),
    )
    monkeypatch.setattr(
        close_out_mod, "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )

    def record(item_id, receipt: MergeReceipt, *, project: str) -> str:
        recorded.update(item_id=item_id, receipt=receipt, project=project)
        return ""

    monkeypatch.setattr(close_out_mod.receipts, "record", record)
    return recorded


def test_landing_records_the_merge_receipt_the_terminal_gate_reads(monkeypatch):
    """The queue merge happens on GitHub, so nothing local records it.

    Without this receipt the terminal QA gate has no landing identity to
    compare blocking runs against and every queue-landed item strands.
    """
    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, members=("YOK-200",),
        head_sha=COMBINED_SHA, run_url="https://runs/1",
    )
    recorded = _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.merge_sha == MERGE_SHA
    assert outcome.batch == batch
    assert outcome.warnings == ()
    assert recorded["item_id"] == 7
    assert recorded["project"] == "yoke"
    assert recorded["receipt"] == MergeReceipt(
        branch="YOK-200", target="main",
        commit_sha=LANE_SHA, merge_sha=MERGE_SHA,
    )


def test_unresolved_batch_still_records_the_lane_head(monkeypatch):
    """An unreadable train is a warning, not a lost landing identity."""
    recorded = _wire(
        monkeypatch, batch=None, batch_warning="merge_group run lookup failed",
    )

    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.merge_sha == ""
    assert "merge_group run lookup failed" in outcome.warnings
    assert recorded["receipt"].commit_sha == LANE_SHA


def test_bookkeeping_failures_degrade_to_warnings(monkeypatch):
    """The merge already landed; refusing the bookkeeping cannot undo it."""
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
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

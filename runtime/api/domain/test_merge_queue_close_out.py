"""A landed queue member must record what its merge is answerable for."""

from __future__ import annotations

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.standalone_item_merge_receipt import MergeReceipt
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
COMBINED_SHA = "h" * 40
MERGE_SHA = "m" * 40


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
    touched=("runtime/api/thing.py",),
    files_error=None,
):
    recorded: dict = {}
    monkeypatch.setattr(close_out_mod, "stamp_merged_at", lambda item_id: None)
    monkeypatch.setattr(
        close_out_mod, "observe_batch",
        lambda ctx, *, pr_num, member_snapshot, drift_check=None: (
            batch,
            batch_warning,
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

    def record(item_id, receipt: MergeReceipt, *, project: str) -> str:
        recorded.update(item_id=item_id, receipt=receipt, project=project)
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
        touched_files=("runtime/api/thing.py",),
    )


def test_landing_carries_the_file_set_the_evidence_record_needs(monkeypatch):
    """Nothing local can diff a queue landing, so the pull request answers.

    The item's execution evidence is refused without touched files, so a
    landing that resolves none lands the merge and then strands the item.
    """
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
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
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
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
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
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
    assert "merge_group run lookup failed" in outcome.warnings
    assert recorded["receipt"].commit_sha == LANE_SHA


def test_landing_leaves_lane_retirement_to_terminal_close_out(monkeypatch):
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
    _wire(monkeypatch, batch=batch)

    outcome = close_out_mod.record_landing(
        _ctx("/repo"), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.warnings == ()
    assert outcome.merge_sha == MERGE_SHA


def test_a_landing_with_no_local_checkout_prunes_nothing(monkeypatch):
    """A caller holding no repository has no lane on disk to retire."""
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
    _wire(monkeypatch, batch=batch)
    outcome = close_out_mod.record_landing(
        _ctx(), item_id=7, commit_sha=LANE_SHA, pr_num="42",
    )

    assert outcome.warnings == ()


def test_landing_fast_forwards_main_without_removing_the_lane(monkeypatch):
    batch = BatchReceipt(pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA)
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

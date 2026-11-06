"""Queue close-out preserves durable CI proof and actionable recovery."""

from __future__ import annotations

import pytest

from runtime.api.domain.merge_queue_close_out_test_support import (
    _wire,
    _ctx,
    MERGE_SHA,
    COMBINED_SHA,
    RUN_URL,
    LANE_SHA,
)
from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt, EvidenceFailure


def test_ci_recording_failure_keeps_close_out_retriable(monkeypatch):
    """The merge stays landed, but terminal evidence must wait for CI proof."""
    batch = BatchReceipt(
        pr_num="42",
        merge_sha=MERGE_SHA,
        head_sha=COMBINED_SHA,
        run_url=RUN_URL,
    )
    _wire(monkeypatch, batch=batch)
    monkeypatch.setattr(
        close_out_mod,
        "stamp_merged_at",
        lambda item_id, **_kwargs: "control plane down",
    )
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda item_id, receipt, **_kw: EvidenceFailure(
            "evidence write refused", True, "Restore the evidence writer."
        ),
    )
    monkeypatch.setattr(
        close_out_mod.receipts,
        "record",
        lambda item_id, receipt, **_kw: "merge receipt not recorded: down",
    )

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
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
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
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
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )
    refusal = outcome.ci_evidence_refusal("42", "yoke merge item YOK-200")

    assert "Re-run" not in refusal
    assert "reaches the same answer" in refusal
    assert "Confirm the queue ran that workflow" in refusal


@pytest.mark.parametrize("scope", ["quick", "full", None])
def test_close_out_preserves_resolved_scope_and_command_recovery(monkeypatch, scope):
    from types import SimpleNamespace
    from yoke_core.domain import merge_queue_batch_receipt as receipt_mod

    batch = BatchReceipt(
        pr_num="42", merge_sha=MERGE_SHA, head_sha=COMBINED_SHA, run_url=RUN_URL
    )
    _wire(monkeypatch, batch=batch)
    payloads = []

    def resolve(*_a, **_k):
        if scope is None:
            raise RuntimeError(
                "project has no executable registered full or quick command"
            )
        return scope, "python3 -m pytest", []

    def dispatch(**kwargs):
        payloads.append(kwargs["payload"])
        return SimpleNamespace(success=True)

    monkeypatch.setattr(receipt_mod, "resolve_verification", resolve)
    monkeypatch.setattr(
        receipt_mod,
        "public_item_target",
        lambda _item: SimpleNamespace(public_ref="ITEM-9"),
    )
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda item, receipt: receipt_mod.record_batch_evidence(
            item, receipt, dispatch=dispatch
        ),
    )
    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=LANE_SHA,
        pr_num="42",
    )
    if scope is not None:
        assert outcome.ci_evidence_error == ""
        assert payloads[0]["scope"] == scope
        assert payloads[0]["command"] == "python3 -m pytest"
    else:
        assert payloads == []
        assert outcome.ci_evidence_retryable is False
        refusal = outcome.ci_evidence_refusal("42", "yoke merge item ITEM-9")
        assert "yoke qa registered-command set" in refusal
        assert "re-run" not in refusal.lower()

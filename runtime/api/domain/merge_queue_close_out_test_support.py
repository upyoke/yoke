# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
    landing_merge=MERGE_SHA,
):
    recorded: dict = {}
    monkeypatch.setattr(
        close_out_mod, "repoint_to_landing_carrier", lambda *_a, **_kw: ""
    )
    # The member's own first-parent merge, which the batch's merge never replaces.
    monkeypatch.setattr(close_out_mod, "_landing_merge", lambda *_a: landing_merge)
    monkeypatch.setattr(
        "yoke_core.domain.merge_landing_proof.verified_landing_identity",
        lambda _repo, _target, candidate, reported="": reported or candidate,
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_landing_proof.verified_target_sha",
        lambda *_a: MERGE_SHA,
    )
    monkeypatch.setattr(
        close_out_mod, "stamp_merged_at", lambda item_id, **_kwargs: None
    )
    # No receipt recorded yet, so every case here exercises the derivation.
    monkeypatch.setattr(
        close_out_mod,
        "read_recorded_batch",
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
        close_out_mod,
        "observe_batch",
        lambda ctx, *, pr_num, member_snapshot, drift_check=None, landed_merge_sha="": (
            batch,
            failure,
        ),
    )
    monkeypatch.setattr(
        close_out_mod,
        "record_batch_evidence",
        lambda item_id, receipt, **_kw: None,
    )
    monkeypatch.setattr(
        close_out_mod,
        "read_pr_changed_files",
        lambda ctx, pr_num: (touched, files_error),
    )

    def stamp(item_id, **kwargs):
        recorded.update(stamped={"item_id": item_id, **kwargs})
        return None

    monkeypatch.setattr(close_out_mod, "stamp_merged_at", stamp)

    def record(item_id, receipt: MergeReceipt) -> str:
        recorded.update(item_id=item_id, receipt=receipt)
        return ""

    monkeypatch.setattr(close_out_mod.receipts, "record", record)
    monkeypatch.setattr(close_out_mod, "fast_forward_main_checkout", lambda *_a: "")
    return recorded

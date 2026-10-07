"""The close-out receipt names the commit the queue merged.

A cached lane head is the commit the lane last recorded. A rebase before
landing, and a correction that lands after an earlier merge, both leave
that cache behind the commit the landing record observed.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import merge_queue_close_out as close_out_mod
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt
from yoke_core.domain.merge_queue_landed_candidate import landed_candidate_head
from yoke_core.domain.merge_queue_landing_outcome import close_out
from yoke_core.domain.merge_queue_landing_record_state import LANDED
from yoke_core.domain.item_merge_receipts import MergeReceipt
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

CACHED = "a" * 40
REBASED = "b" * 40
CORRECTION = "c" * 40
FIRST_MERGE = "m" * 40
CORRECTION_MERGE = "n" * 40


def _ctx() -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-3739", target="main"),
        repo_root="",
        project="yoke",
    )


def _record(head: str, *, state: str = LANDED) -> dict:
    return {
        "public_ref": f"ITEM-{7}",
        "project_id": 1,
        "pr_number": "42",
        "state": state,
        "head_sha": head,
        "queue_holding": "neither",
        "queue_entry_state": "absent",
        "merge_when_ready": "cleared",
        "failed_checks": [],
    }


def _dispatch(record):
    def dispatch(**_kwargs):
        return SimpleNamespace(
            success=True,
            result={"record": record},
            error=None,
        )

    return dispatch


def _wire(monkeypatch, *, merge_sha: str):
    recorded: dict = {}
    monkeypatch.setattr(
        close_out_mod,
        "stamp_merged_at",
        lambda item_id, **_kwargs: None,
    )
    monkeypatch.setattr(
        close_out_mod,
        "read_recorded_batch",
        lambda item_id, *, pr_num: None,
    )
    monkeypatch.setattr(
        close_out_mod,
        "observe_batch",
        lambda ctx, *, pr_num, member_snapshot, drift_check=None, landed_merge_sha="": (
            BatchReceipt(
                pr_num=pr_num,
                merge_sha=merge_sha,
                head_sha="h" * 40,
                run_url="https://runs/42",
            ),
            None,
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
        lambda ctx, pr_num: (("runtime/api/thing.py",), None),
    )
    monkeypatch.setattr(
        close_out_mod,
        "fast_forward_main_checkout",
        lambda *_a: "",
    )

    def record(item_id, receipt: MergeReceipt) -> str:
        recorded.update(item_id=item_id, receipt=receipt)
        return ""

    monkeypatch.setattr(close_out_mod.receipts, "record", record)
    return recorded


def test_landed_record_names_its_candidate_head():
    head, gap = landed_candidate_head(f"ITEM-{7}", dispatch=_dispatch(_record(REBASED)))

    assert gap == ""
    assert head == REBASED


def test_landed_record_without_a_head_does_not_invent_one():
    head, gap = landed_candidate_head(f"ITEM-{7}", dispatch=_dispatch(_record("")))

    assert head == ""
    assert "names no candidate head" in gap


def test_rebase_before_landing_receipt_names_the_landed_head(monkeypatch):
    recorded = _wire(monkeypatch, merge_sha=FIRST_MERGE)

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=CACHED,
        pr_num="42",
        resolve_landed_head=lambda _item: (REBASED, ""),
    )

    assert outcome.receipt_error == ""
    assert recorded["receipt"].commit_sha == REBASED
    assert recorded["receipt"].merge_sha == FIRST_MERGE
    assert recorded["receipt"].commit_sha != CACHED


def test_correction_after_first_merge_receipt_names_the_landed_head(monkeypatch):
    recorded = _wire(monkeypatch, merge_sha=CORRECTION_MERGE)

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=CACHED,
        pr_num="42",
        resolve_landed_head=lambda _item: (CORRECTION, ""),
    )

    assert outcome.receipt_error == ""
    assert recorded["receipt"].commit_sha == CORRECTION
    assert recorded["receipt"].merge_sha == CORRECTION_MERGE
    assert recorded["receipt"].commit_sha != CACHED


def test_missing_landing_head_is_not_filled_from_the_cached_lane(monkeypatch):
    recorded = _wire(monkeypatch, merge_sha=FIRST_MERGE)

    outcome = close_out_mod.record_landing(
        _ctx(),
        item_id=7,
        commit_sha=CACHED,
        pr_num="42",
        resolve_landed_head=lambda _item: ("", "landing record has no observation"),
    )

    assert "receipt" not in recorded
    assert outcome.receipt_commit_sha == ""
    assert CACHED not in outcome.receipt_error
    assert "cached lane head is not recorded" in outcome.receipt_error
    assert outcome.ci_evidence_refusal("42") == outcome.receipt_error


def test_queue_close_out_publishes_the_landing_record_head(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_outcome.record_landing",
        lambda ctx, **kwargs: _applied(kwargs),
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_outcome.landed_candidate_head",
        lambda item_id, **_kwargs: (REBASED, ""),
    )

    outcome = close_out(
        _ctx(),
        item_id=7,
        public_ref="YOK-3739",
        commit_sha=CACHED,
        pr_num="42",
        member_refs=(),
        drift=None,
        resume_command="yoke merge item YOK-3739",
        warnings=[],
    )

    assert outcome.ok is True
    assert outcome.commit_sha == REBASED
    assert outcome.merge_sha == FIRST_MERGE


def _applied(kwargs: dict):
    from yoke_core.domain.merge_queue_close_out import QueueCloseOut

    head, gap = kwargs["resolve_landed_head"](kwargs["item_id"])
    return QueueCloseOut(
        merge_sha=FIRST_MERGE,
        receipt_commit_sha=head,
        receipt_error="" if head else gap,
    )


def test_landed_record_rejects_numeric_item_identity():
    record = _record(REBASED)
    record["item_id"] = 7
    record.pop("public_ref")

    head, reason = landed_candidate_head(f"ITEM-{7}", dispatch=_dispatch(record))

    assert head == ""
    assert "landing record response was invalid" in reason
    assert "public_ref" in reason

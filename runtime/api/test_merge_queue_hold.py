"""Holding a candidate: both states cleared, read back, or not held at all."""

import pytest

from yoke_core.domain import merge_queue_hold as hold_mod
from yoke_core.domain.merge_queue_readback_outcomes import (
    HOLD_ALREADY_CLEAR,
    HOLD_ALREADY_LANDED,
    HOLD_HELD,
    HOLD_LANDED_DURING_HOLD,
    HOLD_NOT_HELD,
    HOLD_UNVERIFIED,
)
from yoke_core.domain.merge_queue_readiness import classify_readiness
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueEntryResult,
    QueueMember,
)
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

PR = "42"
TARGET = "main"
LANE_HEAD = "a" * 40
MERGE_COMMIT = "b" * 40


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="PRJ-9", target=TARGET), project="prj")


def _readiness(
    *,
    armed: bool = False,
    entry: bool = False,
    merged: bool = False,
    queue_readable: bool = True,
):
    state = PrLandingState(
        merged=merged,
        closed=merged,
        auto_merge_active=armed,
        head_sha=LANE_HEAD,
        merged_at="2026-09-15T00:00:00Z" if merged else "",
        merge_commit_sha=MERGE_COMMIT if merged else "",
    )
    members = [QueueMember(pr_num=PR, head_ref="PRJ-9", state="AWAITING_CHECKS")]
    return classify_readiness(
        pr_number=PR,
        target=TARGET,
        state=state,
        members=(members if entry else []) if queue_readable else None,
        queue_error="" if queue_readable else "queue read failed",
    )


class _Recorder:
    """Stand-in GitHub: records mutations and serves scripted readbacks."""

    def __init__(self, reads, *, disarm=True, dequeue=True):
        self._reads = list(reads)
        self.calls: list[str] = []
        self._disarm = disarm
        self._dequeue = dequeue

    def read(self, _ctx, *, pr_number, target):
        self.calls.append("read")
        return self._reads.pop(0) if len(self._reads) > 1 else self._reads[0]

    def leave(self, _ctx, pr_num):
        self.calls.append("disarm")
        return QueueEntryResult(
            success=self._disarm,
            pr_num=pr_num,
            error_detail=None if self._disarm else "provider refused the disarm",
        )

    def dequeue(self, _ctx, pr_num):
        self.calls.append("dequeue")
        return QueueEntryResult(
            success=self._dequeue,
            pr_num=pr_num,
            error_detail=None if self._dequeue else "provider refused the dequeue",
        )


@pytest.fixture()
def wire(monkeypatch):
    def _wire(reads, **kwargs):
        recorder = _Recorder(reads, **kwargs)
        monkeypatch.setattr(hold_mod, "read_merge_queue_readiness", recorder.read)
        monkeypatch.setattr(hold_mod, "leave_merge_queue", recorder.leave)
        monkeypatch.setattr(hold_mod, "dequeue_pull_request", recorder.dequeue)
        return recorder

    return _wire


def _hold():
    return hold_mod.hold_landing(_ctx(), pr_number=PR, target=TARGET)


def test_armed_candidate_is_disarmed_and_verified_clear(wire):
    recorder = wire([_readiness(armed=True), _readiness()])
    outcome = _hold()
    assert outcome.outcome == HOLD_HELD
    assert outcome.held is True
    assert "dequeue" not in recorder.calls
    assert recorder.calls.count("disarm") == 1


def test_enqueued_candidate_is_dequeued_not_merely_disarmed(wire):
    """An entry GitHub already formed consumed the arming; only a dequeue clears it."""
    recorder = wire([_readiness(entry=True), _readiness()])
    outcome = _hold()
    assert outcome.outcome == HOLD_HELD
    assert "dequeue" in recorder.calls
    assert "disarm" not in recorder.calls


def test_entry_formed_between_the_read_and_the_disarm_is_still_dequeued(wire):
    """The consumption race: armed when read, enqueued by the time it acted."""
    recorder = wire([_readiness(armed=True), _readiness(entry=True), _readiness()])
    outcome = _hold()
    assert outcome.outcome == HOLD_HELD
    assert recorder.calls == ["read", "disarm", "read", "dequeue", "read"]


def test_already_clear_candidate_holds_without_mutating_anything(wire):
    recorder = wire([_readiness()])
    outcome = _hold()
    assert outcome.outcome == HOLD_ALREADY_CLEAR
    assert outcome.held is True
    assert recorder.calls == ["read"]


def test_already_merged_candidate_reports_the_commit_github_merged(wire):
    recorder = wire([_readiness(merged=True)])
    outcome = _hold()
    assert outcome.outcome == HOLD_ALREADY_LANDED
    assert outcome.held is False
    assert outcome.merge_commit_sha == MERGE_COMMIT
    assert MERGE_COMMIT in outcome.refusal
    assert recorder.calls == ["read"]


def test_candidate_that_lands_mid_hold_reports_the_landing_not_a_failure(wire):
    wire([_readiness(entry=True), _readiness(merged=True)])
    outcome = _hold()
    assert outcome.outcome == HOLD_LANDED_DURING_HOLD
    assert outcome.merged is True
    assert outcome.merge_commit_sha == MERGE_COMMIT


def test_refused_dequeue_leaves_the_candidate_live_and_says_so(wire):
    recorder = wire([_readiness(entry=True)], dequeue=False)
    outcome = _hold()
    assert outcome.outcome == HOLD_NOT_HELD
    assert outcome.held is False
    assert "provider refused the dequeue" in " ".join(outcome.actions)
    assert "do not push a correction against it" in outcome.refusal
    assert recorder.calls.count("dequeue") == 2


def test_unreadable_queue_is_reported_unverified_rather_than_held(wire):
    wire([_readiness(armed=True, queue_readable=False)])
    outcome = _hold()
    assert outcome.outcome == HOLD_UNVERIFIED
    assert outcome.held is False
    assert "unverified" in outcome.refusal


def test_hold_never_rearms(wire):
    recorder = wire([_readiness(entry=True), _readiness()])
    _hold()
    assert "enter" not in recorder.calls
    assert hold_mod.REARM_RECOVERY.startswith("correct the lane")
